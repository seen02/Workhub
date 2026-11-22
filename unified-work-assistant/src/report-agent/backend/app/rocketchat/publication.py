"""Explicit two-step publication, immutable snapshots and stable retry IDs."""
import hashlib
import json
import threading
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from ..models import ChatDraft, ChatDraftRevision, ChatPublication
from .draft import safe_text
from .review_service import owned_draft
from .workspace import PROJECTS, source_url
from .report_format import format_report

PUBLISH_LOCK = threading.Lock()


class PublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def receipt(row):
    return {"version": row.version, "state": row.state, "url": source_url(row.room_id, row.message_id)}


def preview(db, entity, target):
    if entity.state != "CONFIRMED":
        raise HTTPException(409, "먼저 내용을 확인하고 개인 저장을 완료하세요.")
    items = json.loads(entity.current_data)
    if any(i.get("project") not in PROJECTS or i["status"] == "UNKNOWN" for i in items):
        raise HTTPException(422, "모든 업무의 프로젝트와 상태를 선택하고 저장한 뒤 게시하세요.")
    previous = db.scalar(select(ChatPublication).where(ChatPublication.draft_id == entity.id,
        ChatPublication.state == "SENT", ChatPublication.version < entity.version).order_by(ChatPublication.version.desc()))
    lines = [format_report(items, entity.submitted_at)]
    if previous:
        lines.extend(["", f"수정본 · [이전 게시본]({source_url(previous.room_id, previous.message_id)})"])
    lines.extend(["", f"작성자: {safe_text(entity.author_username)} · 보고 {entity.id[:8]} · v{entity.version} · 확인 후 게시"])
    text = "\n".join(lines)
    # Format updates must not rewrite an already sent/reserved publication.
    existing = db.get(ChatPublication, (entity.id, entity.version))
    if existing:
        if existing.room_id != target["room_id"]:
            raise HTTPException(409, "기존 게시 요청과 대상이 다릅니다.")
        text = existing.text
    if len(text) > 4500:
        raise HTTPException(422, "게시 내용이 너무 깁니다. 업무명·다음 작업·이슈를 줄여 저장해 주세요.")
    digest = hashlib.sha256(f"{target['room_id']}:{entity.version}:{text}".encode()).hexdigest()
    return {"version": entity.version, "target": target["name"], "text": text,
            "preview_hash": digest, "publication": receipt(existing) if existing else None}


def publish(db, draft_id, user, payload, target, authorize, deliver):
    # Single local API process; persistent PK + stable message ID also protect crash/restart retries.
    if not PUBLISH_LOCK.acquire(blocking=False):
        raise HTTPException(409, "다른 게시 요청을 처리 중입니다. 잠시 후 다시 시도하세요.")
    try:
        entity = owned_draft(db, draft_id, user)
        authorize()
        claim = db.execute(update(ChatDraft).where(ChatDraft.id == entity.id,
            ChatDraft.version == payload.version, ChatDraft.state == "CONFIRMED").values(
            updated_at=entity.updated_at).execution_options(synchronize_session=False))
        if claim.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "보고가 변경되었습니다. 저장된 최신 내용으로 게시 미리보기를 다시 확인하세요.")
        db.refresh(entity)
        view = preview(db, entity, target)
        if view["preview_hash"] != payload.preview_hash:
            db.rollback()
            raise HTTPException(409, "게시 대상이나 내용이 변경되었습니다. 미리보기를 다시 확인하세요.")
        row = db.get(ChatPublication, (entity.id, entity.version))
        if row and row.state == "SENT":
            db.commit()
            return {**receipt(row), "already_sent": True}
        if not row:
            if db.scalar(select(ChatPublication).where(ChatPublication.draft_id == entity.id, ChatPublication.state == "PENDING")):
                raise HTTPException(409, "이전 게시 결과를 먼저 확인하세요.")
            row = ChatPublication(draft_id=entity.id, version=entity.version, room_id=target["room_id"],
                message_id="report" + hashlib.sha256(f"{entity.id}:{entity.version}".encode()).hexdigest()[:32],
                text=view["text"], actor_id=user["_id"], state="PENDING")
            db.add(row)
        if row.room_id != target["room_id"] or row.text != view["text"]:
            raise HTTPException(409, "기존 게시 요청과 대상 또는 내용이 다릅니다.")
        db.commit()  # Persist before network I/O; never auto-publish on save or startup.
        authorize()
        try:
            deliver(row)
        except Exception as exc:
            raise HTTPException(503, "게시 결과를 확인하지 못했습니다. 같은 보고의 게시 버튼으로 재시도하세요. 중복 메시지는 만들지 않습니다.") from exc
        row.state = "SENT"
        db.add(ChatDraftRevision(draft_id=entity.id, actor_id=user["_id"], version=entity.version,
            action="PUBLISH", before_data="{}", after_data=json.dumps(receipt(row)),
            reason="사용자가 게시 미리보기 확인 후 팀 보고방에 게시"))
        db.commit()
        return {**receipt(row), "already_sent": False}
    finally:
        PUBLISH_LOCK.release()
