"""Explicit, own-message historical import. Preview never persists or invokes AI."""
import hashlib
import json
import re
import threading
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models import ChatDraft
from .commands import command_for
from .query import KST
from .review_service import register_draft, serialize
from .workspace import source_url

IMPORT_SLOT = threading.BoundedSemaphore(1)
PAGE_SIZE = 50
MAX_SCAN = 2000


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_id: str = Field(min_length=1, max_length=100)
    start: date
    end: date
    offset: int = Field(default=0, ge=0, le=MAX_SCAN-PAGE_SIZE)
    as_of: datetime | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.end < self.start or (self.end-self.start).days > 30 or self.end > datetime.now(KST).date():
            raise ValueError("과거 또는 오늘 날짜에서 최대 31일을 선택하세요.")
        if self.offset % PAGE_SIZE:
            raise ValueError("미리보기 페이지가 올바르지 않습니다.")
        if self.offset and self.as_of is None:
            raise ValueError("이어서 조회할 때 최초 조회 시각이 필요합니다.")
        if self.as_of and (self.as_of.tzinfo is None or self.as_of > datetime.now(timezone.utc) + timedelta(seconds=5)):
            raise ValueError("조회 기준 시각이 올바르지 않습니다.")
        return self


class ImportInput(PreviewInput):
    message_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def identity(room_id, message_id):
    return hashlib.sha256(f"local-rocketchat:{room_id}:{message_id}".encode()).hexdigest()


def boundaries(payload):
    start = datetime.combine(payload.start, time.min, KST)
    end = datetime.combine(payload.end + timedelta(days=1), time.min, KST) - timedelta(milliseconds=1)
    return start, min(end, payload.as_of or datetime.now(timezone.utc))


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Source time must have a timezone")
    return stamp


def fingerprint(message):
    # Any source edit, including edit time, invalidates the preview selection.
    value = {key: message.get(key) for key in ("_id", "rid", "u", "msg", "ts", "editedAt")}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def eligible(message, user, payload):
    if (message.get("rid") != user["room_id"] or message.get("u", {}).get("_id") != user["_id"]
            or message.get("u", {}).get("username") != user["username"] or message.get("t")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", message.get("_id", "")):
        return None
    try:
        start, end = boundaries(payload)
        if not start <= timestamp(message["ts"]) <= end:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    raw = message.get("msg", "").strip()
    # Drop operational commands, not ordinary chat. The person chooses what is a report.
    command = command_for({**message, "tmid": None}, user["room_id"], {user["username"]}, "")
    if command and command[0] != "report":
        return None
    if command and command[0] == "report":
        raw = command[1]
    return raw if 5 <= len(raw) <= 4000 else None


def check_room(payload, user):
    if payload.room_id != user["room_id"]:
        raise HTTPException(403, "현재 허용된 로컬 비공개 테스트방만 가져올 수 있습니다.")


def preview_messages(db, user, payload, fetch):
    check_room(payload, user)
    start, end = boundaries(payload)
    if end < start:
        raise HTTPException(422, "조회 기준 시각과 기간을 다시 선택하세요.")
    snapshot = payload.model_copy(update={"as_of": end})
    history_endpoint = "im.history" if user.get("room_type") == "d" else "groups.history"
    messages = fetch(history_endpoint, {"roomId": user["room_id"], "oldest": start.isoformat(),
        "latest": end.isoformat(), "inclusive": "true", "count": PAGE_SIZE, "offset": payload.offset})["messages"]
    candidates = [(m, eligible(m, user, snapshot)) for m in messages]
    ids = [identity(user["room_id"], m["_id"]) for m, raw in candidates if raw]
    existing = {d.id: d for d in db.scalars(select(ChatDraft).where(ChatDraft.id.in_(ids)))} if ids else {}
    items = []
    for m, raw in candidates:
        if not raw:
            continue
        draft_id = identity(user["room_id"], m["_id"])
        old = existing.get(draft_id)
        items.append({"message_id": m["_id"], "fingerprint": fingerprint(m), "text": raw,
            "author": user["username"], "submitted_at": timestamp(m["ts"]).astimezone(KST).replace(tzinfo=None).isoformat(),
            "source_url": source_url(user["room_id"], m["_id"]),
            "existing": old.state if old else None, "review_url": f"http://127.0.0.1:8003/#{draft_id}" if old else None})
    capped = len(messages) == PAGE_SIZE and payload.offset+PAGE_SIZE >= MAX_SCAN
    return {"items": items, "as_of": end.isoformat(), "scanned": len(messages),
        "next_offset": payload.offset+PAGE_SIZE if len(messages) == PAGE_SIZE and not capped else None,
        "scan_limit_reached": capped, "scope": "본인 · 개인보고 방 · 텍스트만", "llm_used": False, "persisted": False}


def import_message(db, user, payload, fetch, parse, model, reauthorize):
    check_room(payload, user)
    if not IMPORT_SLOT.acquire(blocking=False):
        raise HTTPException(429, "다른 가져오기를 처리 중입니다. 완료 후 다시 시도하세요.")
    try:
        def read_source():
            msg = fetch("chat.getMessage", {"msgId": payload.message_id})["message"]
            raw = eligible(msg, user, payload)
            if not raw:
                raise HTTPException(404, "본인·선택 기간의 텍스트 메시지만 가져올 수 있습니다.")
            if fingerprint(msg) != payload.fingerprint:
                raise HTTPException(409, "원문이 변경되었습니다. 미리보기를 다시 조회해 주세요.")
            return msg, raw
        message, raw = read_source()
        old = db.get(ChatDraft, identity(user["room_id"], payload.message_id))
        if old:
            if old.author_id != user["_id"] or old.raw_message != raw:
                raise HTTPException(409, "이미 저장된 초안과 원문이 다릅니다. 기존 보고를 확인하세요.")
            return {"created": False, "draft": serialize(db, old)}
        db.rollback()  # Do not hold a DB read transaction while waiting for Gemma.
        parsed = parse(raw)
        if reauthorize() != user:
            raise HTTPException(403, "가져오는 동안 접근 권한이 변경되었습니다.")
        message, raw = read_source()  # Source edits/deletions during AI must not be silently saved.
        try:
            saved = register_draft(db, message, raw, parsed, model, import_reason=f"이전 보고 선택 가져오기 · {payload.start}~{payload.end}")
        except IntegrityError:
            db.rollback()
            saved = db.get(ChatDraft, identity(user["room_id"], payload.message_id))
            if not saved or saved.author_id != user["_id"] or saved.raw_message != raw:
                raise HTTPException(409, "동시 가져오기 충돌입니다. 기존 보고를 확인하세요.")
            return {"created": False, "draft": serialize(db, saved)}
        return {"created": True, "draft": serialize(db, saved)}
    finally:
        IMPORT_SLOT.release()
