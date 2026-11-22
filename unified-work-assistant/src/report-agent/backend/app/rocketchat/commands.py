"""Small explicit chat vocabulary; ordinary conversation is not captured as a report."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChatDraft, ChatDraftRevision
from .review_service import ReviewEdit, save_review

HELP = (
    "[업무비서 사용법]\n"
    "1. `보고 오늘 자료조사를 완료했고 화면은 수정 중입니다`\n"
    "2. 초안이 맞으면 `✅ 이대로 보고` 링크를 누름\n"
    "3. 다시 찾을 때 `오늘 보고` / `이번 주 보고` / `미완료 보고`\n\n"
    "검색 예: `조회 이번 주 공간정보`\n"
    "고칠 때만 [수정 화면](http://127.0.0.1:8003)을 열어 주세요.\n"
    "본인 확정 보고만 검색하며 결과는 본인의 개인보고 방에 표시됩니다."
)


def command_for(message: dict, room: str, allowed: set[str], bot_id: str):
    user = message.get("u", {})
    if message.get("rid") != room or user.get("_id") == bot_id or user.get("username") not in allowed or message.get("t"):
        return None
    text = message.get("msg", "").strip()
    if re.fullmatch(r"!?확정(?:\s+[a-f0-9]{8})?", text):
        return "confirm", ""
    if text in {"도움말", "!도움말", "사용법", "도움"}:
        return "help", ""
    if message.get("tmid"):
        return None
    if text in {"보고", "!보고"}:
        return "publish", ""
    match = re.match(r"^!?보고(?:\s+([\s\S]*))?$", text)
    if match:
        return "report", (match.group(1) or "").strip()
    if re.match(r"^!?조회(?:\s|$)", text):
        return "query", text
    if re.search(r"오늘|어제|이번\s*주|지난\s*주|미완료|완료하지\s*않은|안\s*끝난", text) and re.search(r"보고|보여\s*줘|알려\s*줘|찾아\s*줘", text):
        return "query", text
    return None


def manager_command_for(message: dict, room: str, manager: str, bot_id: str):
    user = message.get("u", {})
    if (message.get("rid") != room or user.get("_id") == bot_id
            or user.get("username") != manager or message.get("tmid") or message.get("t")):
        return None
    text = message.get("msg", "").strip()
    if text in {"도움말", "!도움말", "관리자 도움말"}:
        return "manager_help", ""
    # This is a dedicated two-member manager room. Let Gemma classify natural
    # questions instead of requiring a small fixed command vocabulary.
    if 1 <= len(text) <= 500:
        return "manager", text
    return None


def team_query_command_for(message: dict, room: str, allowed: set[str], bot_id: str):
    """Accept report lookup questions from members of the shared report room."""
    user = message.get("u", {})
    if (message.get("rid") != room or user.get("_id") == bot_id
            or user.get("username") not in allowed or message.get("tmid") or message.get("t")):
        return None
    text = message.get("msg", "").strip()
    if text in {"도움말", "!도움말", "업무비서 도움말", "조회 도움말"}:
        return "team_help", ""
    # The shared room also contains confirmed reports. Only human messages that
    # look like lookup questions are handled, so normal conversation is ignored.
    subject = re.search(r"보고|업무|프로젝트|직원|사원|리스크|진행|현황", text)
    request = re.search(r"보여\s*줘|보여주세요|알려\s*줘|알려주세요|조회|찾아\s*줘|어디까지|누구|뭐|무엇|현황|진행사항|리스크|\?$", text)
    if 2 <= len(text) <= 500 and subject and request:
        return "team_query", text
    return None


def confirm_from_chat(db: Session, message: dict) -> str:
    # Actor identity comes from Rocket.Chat's authenticated message envelope, never its text.
    user = {"_id": message["u"]["_id"], "username": message["u"]["username"], "room_id": message["rid"]}
    request_key = f"로켓챗 확정 요청:{message['_id']}"
    previous = db.scalar(select(ChatDraft).join(ChatDraftRevision, ChatDraftRevision.draft_id == ChatDraft.id).where(
        ChatDraft.author_id == user["_id"], ChatDraft.room_id == user["room_id"],
        ChatDraftRevision.actor_id == user["_id"], ChatDraftRevision.reason == request_key))
    if previous:
        return f"[보고 확정 완료]\n이미 처리한 확정 요청이에요. 중복 저장하지 않았습니다. [보고 보기](http://127.0.0.1:8003/#{previous.id})"
    stmt = select(ChatDraft).where(ChatDraft.author_id == user["_id"], ChatDraft.room_id == user["room_id"])
    code = re.fullmatch(r"!?확정\s+([a-f0-9]{8})", message.get("msg", "").strip())
    if code:
        stmt = stmt.where(ChatDraft.id.startswith(code.group(1)))
    elif message.get("tmid"):
        # A user can reply either to the source report or to the bot's visible preview.
        parent = message["tmid"]
        if parent.startswith("draft"):
            source_ids = db.scalars(select(ChatDraft.message_id).where(
                ChatDraft.author_id == user["_id"], ChatDraft.room_id == user["room_id"]))
            parent = next((source for source in source_ids if "draft" + hashlib.sha256(
                f"{user['room_id']}:{source}".encode()).hexdigest()[:24] == parent), "")
        stmt = stmt.where(ChatDraft.message_id == parent)
    else:
        stmt = stmt.where(ChatDraft.state == "DRAFT")
    matches = db.scalars(stmt.order_by(ChatDraft.created_at.desc()).limit(2)).all()
    if not matches:
        return "확정할 초안이 없어요. 이미 저장했다면 `오늘 보고`, 새로 작성하려면 `보고 업무내용`을 입력해 주세요."
    if len(matches) != 1:
        return "대기 중인 초안이 여러 개입니다. 최신 미리보기의 `✅ 이대로 보고`를 누르거나 [내 보고 선택](http://127.0.0.1:8003)을 열어 주세요."
    draft = matches[0]
    link = f"http://127.0.0.1:8003/#{draft.id}"
    if draft.state == "CONFIRMED":
        return f"이미 확정된 보고예요. 중복 저장하지 않았습니다. [보고 보기]({link})"
    if db.scalar(select(ChatDraftRevision.id).where(ChatDraftRevision.draft_id == draft.id, ChatDraftRevision.action == "IMPORT")):
        return f"가져온 이전 보고는 [내용 확인·수정]({link}) 화면에서 확인하고 저장해 주세요. 채팅에서는 임의로 확정하지 않았습니다."
    if draft.version != 1:
        return f"웹에서 수정한 초안이 있어요. 채팅에 보인 최초 초안과 다를 수 있으니 [수정 내용 확인 후 확정]({link})해 주세요."
    sent_at = datetime.fromisoformat(message["ts"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=9))).replace(tzinfo=None)
    if sent_at < draft.created_at:
        return "초안을 만들기 전에 보낸 확정 요청이라 저장하지 않았어요. 초안 내용을 읽고 다시 `확정`해 주세요."
    payload = ReviewEdit(version=1, items=json.loads(draft.current_data), reason=request_key)
    try:
        save_review(db, draft, user, payload, True)
    except HTTPException as exc:
        db.rollback()
        return f"저장하지 않았어요: {exc.detail}\n[내용 확인·수정]({link})"
    return f"[보고 확정 완료]\n{len(payload.items)}개 업무를 저장했어요. 중복 보고는 만들지 않습니다.\n이제 `오늘 보고`라고 입력하면 다시 볼 수 있어요.\n[수정·변경 이력]({link}) · 실제 회사 채널에는 발송하지 않았습니다."
