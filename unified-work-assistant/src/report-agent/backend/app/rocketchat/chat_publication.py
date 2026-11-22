"""Publish only an own, actually displayed, unchanged personal-room preview."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from ..models import ChatDraft, ChatDraftRevision, ChatPublication
from .publication import PublishInput, preview, publish
from .report_format import format_report
from .review_service import ReviewEdit, save_review
from .workspace import PROJECTS, private_members_ok


def personal_preview(entity, model, elapsed):
    items = json.loads(entity.current_data)
    # Keep this message copyable as a report: no links, commands or model notes.
    return format_report(items, entity.submitted_at)


def personal_actions(entity, model, elapsed, review_url=None, publish_url=None):
    items = json.loads(entity.current_data)
    ready = all(i.get("project") in PROJECTS and i["status"] != "UNKNOWN" for i in items)
    action = (f"[✅ 이대로 보고]({publish_url}) · [✏️ 내용 수정]({review_url})\n"
              "키보드로 하려면 `보고` 입력 후 Enter") if ready else (
              "프로젝트 또는 상태 확인이 필요합니다. 아래 수정 사이트에서 확인해 주세요.")
    detail = ("\n\n수정한 경우에는 사이트에서 저장 → 보고방에 게시" if ready else
              f"\n\n[✏️ 보고 내용 수정하기]({review_url or f'http://127.0.0.1:8003/#{entity.id}'})")
    return ("**보고 확인·제출**\n"
            f"{action}{detail}\n\n"
            f"개인보고 방 미리보기 · 아직 팀 보고방 미게시 · {model} · {elapsed:.1f}초")


def mark_displayed(db, message):
    draft_id = hashlib.sha256(f"local-rocketchat:{message['rid']}:{message['_id']}".encode()).hexdigest()
    entity = db.get(ChatDraft, draft_id)
    # Called only AFTER a successful bot message update. Old/web-edited/imported
    # drafts never gain permission to publish just because the service restarts.
    if not entity or entity.version != 1 or entity.state != "DRAFT":
        return
    if db.scalar(select(ChatDraftRevision.id).where(ChatDraftRevision.draft_id == draft_id,
            ChatDraftRevision.action.in_(["IMPORT", "CHAT_PREVIEW"]))):
        return
    db.add(ChatDraftRevision(draft_id=draft_id, version=1, actor_id=entity.author_id,
        action="CHAT_PREVIEW", before_data="{}", after_data=entity.current_data,
        reason="개인보고 방에 보고 양식 미리보기 표시 완료"))
    db.commit()


def publish_from_chat(db, message, target, authorize, deliver):
    user = {"_id": message["u"]["_id"], "username": message["u"]["username"], "room_id": message["rid"]}
    request_key = f"로켓챗 게시 요청:{message['_id']}"
    owned = (ChatDraft.author_id == user["_id"], ChatDraft.room_id == user["room_id"])
    # Bind a command durably in the same commit that confirms its snapshot.
    # A crash/retry must never select a different report for the same command.
    claim = db.scalar(select(ChatDraftRevision).join(ChatDraft).where(*owned,
        ChatDraftRevision.actor_id == user["_id"], ChatDraftRevision.reason == request_key))
    if claim:
        entity = db.get(ChatDraft, claim.draft_id)
        if entity.version != claim.version or entity.current_data != claim.after_data:
            raise HTTPException(409, "보고가 수정되었습니다. 수정 화면에서 최신 내용을 확인하고 게시하세요.")
    else:
        stmt = select(ChatDraft, ChatDraftRevision).join(ChatDraftRevision).where(*owned,
            ChatDraftRevision.action == "CHAT_PREVIEW")
        matches = db.execute(stmt.order_by(ChatDraftRevision.id.desc())).all()
        pending = [(d, r) for d, r in matches if not db.scalar(select(ChatPublication).where(
            ChatPublication.draft_id == d.id, ChatPublication.state == "SENT"))]
        candidates = pending or matches[:1]
        if not candidates:
            return "개인보고 방에서 확인한 새 초안이 없습니다. `보고 업무내용`으로 작성해 주세요. 기존 보고는 [수정 화면](http://127.0.0.1:8003)에서 확인·게시할 수 있어요."
        # The newest unposted preview is the single active draft. Older drafts remain
        # in history but never require a user-visible selection code.
        entity, visible = candidates[0]
        link = f"http://127.0.0.1:8003/#{entity.id}"
        existing = db.get(ChatPublication, (entity.id, entity.version))
        if existing and existing.state == "SENT":
            return "이미 게시된 보고입니다. 중복 게시하지 않았습니다."
        confirmed = db.scalar(select(ChatDraftRevision).where(ChatDraftRevision.draft_id == entity.id,
            ChatDraftRevision.version == entity.version, ChatDraftRevision.action == "CONFIRM",
            ChatDraftRevision.reason.startswith("로켓챗 게시 요청:")))
        if entity.current_data != visible.after_data or (entity.version != 1 and not confirmed):
            return f"웹에서 수정·저장된 보고입니다. 개인보고 방의 최초 미리보기와 다를 수 있어요. [수정 내용 확인 후 게시]({link})해 주세요."
        sent_at = datetime.fromisoformat(message["ts"].replace("Z", "+00:00")).astimezone(
            timezone(timedelta(hours=9))).replace(tzinfo=None)
        if sent_at < visible.created_at:
            return "미리보기를 표시하기 전에 보낸 요청입니다. 내용을 확인한 뒤 다시 `보고`를 입력해 주세요."
        items = json.loads(visible.after_data)
        if any(i.get("project") not in PROJECTS or i["status"] == "UNKNOWN" for i in items):
            return f"프로젝트와 상태를 먼저 확인해 주세요. [내용 수정·저장·게시]({link})"
        authorize()
        if entity.version == 1:
            entity = save_review(db, entity, user, ReviewEdit(version=1, items=items, reason=request_key), True)
        else:
            # A new explicit retry of a previously reserved chat publication.
            db.add(ChatDraftRevision(draft_id=entity.id, version=entity.version, actor_id=user["_id"],
                action="CHAT_RETRY", before_data=entity.current_data, after_data=entity.current_data, reason=request_key))
            db.commit()
    view = preview(db, entity, target)
    result = publish(db, entity.id, user, PublishInput(version=entity.version, preview_hash=view["preview_hash"]),
                     target, authorize, deliver)
    return ("**✅ 팀 업무보고 방에 게시했습니다.**" if not result["already_sent"] else "이미 게시했습니다. 중복 게시하지 않았어요.") + f"\n[게시된 보고 보기]({result['url']})"


def authorize_chat_target(api, config, user, room_id):
    target = config.get("channels", {}).get("reports")
    if config.get("personal_owner") != user["username"] or not target:
        raise HTTPException(403, "본인의 개인보고 방에서만 게시할 수 있습니다.")
    if config.get("room_type") == "d":
        members = api.call("GET", "im.members", params={"roomId": room_id, "count": 3})
        if not private_members_ok(members, user["username"], config["username"]):
            raise HTTPException(403, "본인의 report-bot 1:1 대화에서만 게시할 수 있습니다.")
    else:
        own = (config.get("personal_rooms", {}).get(user["username"])
               or config.get("legacy_personal_rooms", {}).get(user["username"]))
        if not own or own["room_id"] != room_id:
            raise HTTPException(403, "등록된 이전 개인 보고방에서만 게시할 수 있습니다.")
    room = api.call("GET", "groups.info", params={"roomId": target["room_id"]})["group"]
    if room.get("_id") != target["room_id"] or room.get("t") != "p" or room.get("encrypted") or room.get("teamId") != config.get("team_id"):
        raise HTTPException(403, "팀 보고방 구성 또는 권한이 변경되었습니다.")
    offset = 0
    while True:
        result = api.call("GET", "groups.members", params={"roomId": target["room_id"], "count": 100, "offset": offset})
        members = result.get("members", [])
        if any(m.get("_id") == user["_id"] and m.get("username") == user["username"] for m in members):
            return
        offset += len(members)
        if not members or offset >= result.get("total", offset):
            raise HTTPException(403, "팀 보고방에 참여한 본인만 게시할 수 있습니다.")
