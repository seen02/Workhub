"""Loopback-only review UI; Rocket.Chat session + source author ownership required."""
import asyncio
import json
import os
import hashlib
import threading
import time
from datetime import date
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..database import get_db
from ..models import ChatDraft, ChatDraftRevision, ChatPublication
from .review_service import ReviewEdit, owned_draft, save_review, serialize
from .query import parse_query, search_reports
from .import_service import PreviewInput, ImportInput, preview_messages, import_message
from .draft import DraftProvider
from ..llm.local import LocalLLMError
from .workspace import PROJECTS, private_members_ok, room_url
from .publication import PublishInput, preview as publication_preview, publish, receipt
from .link_auth import (issue_manager_link, issue_session, verify_link,
                        verify_manager_link, verify_session)
from .manager_service import answer_manager_question, get_manager_dashboard

LOCAL = Path(os.getenv(
    "ROCKETCHAT_LOCAL_PATH",
    Path(__file__).resolve().parents[3] / "rocketchat" / ".local",
))
STATIC = Path(__file__).resolve().parent / "review_ui"
CHAT_URL = os.getenv("ROCKETCHAT_INTERNAL_URL", "http://127.0.0.1:3000").rstrip("/")
app = FastAPI(title="로켓챗 보고 수정·확정", docs_url=None, redoc_url=None)
AUTH_CACHE = {}
AUTH_CACHE_LOCK = threading.Lock()
AUTH_CACHE_SECONDS = 20
BOT_AUTH = {}
BOT_AUTH_LOCK = threading.Lock()


@app.exception_handler(IntegrityError)
async def duplicate_or_conflict(request, exc):
    return JSONResponse(status_code=409, content={"detail": "중복 저장 또는 동시 수정 충돌입니다. 목록을 새로 불러와 확인하세요."})


def config():
    return json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))


def chat_request(method, endpoint, headers=None, body=None, params=None):
    try:
        with httpx.Client(base_url=CHAT_URL, timeout=10, trust_env=False) as client:
            response = client.request(method, "/api/v1/" + endpoint, headers=headers, json=body, params=params)
        if response.status_code == 429:
            raise HTTPException(429, "로켓챗의 1분 요청 한도를 초과했습니다. 최대 1분 후 다시 시도하세요. 연속 새로고침·로그인은 피해주세요.")
        if response.status_code in (400, 401, 403, 404):
            raise HTTPException(401, "로켓챗 로그인 또는 테스트방 접근 권한을 확인하세요.")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "로컬 Rocket.Chat 연결을 확인하세요.") from exc


def bot_headers():
    """Reuse one server-side bot login; never expose this token to a browser."""
    now = time.monotonic()
    with BOT_AUTH_LOCK:
        if BOT_AUTH.get("expires", 0) > now:
            return dict(BOT_AUTH["headers"])
        settings = config()
        data = chat_request("POST", "login", body={
            "user": settings["username"], "password": settings["password"],
        })["data"]
        headers = {"X-User-Id": data["userId"], "X-Auth-Token": data["authToken"]}
        BOT_AUTH.update(headers=headers, expires=now + 300)
        return dict(headers)


def require_team_member(user, headers):
    settings = config()
    target = settings.get("channels", {}).get("reports")
    if not target:
        raise HTTPException(503, "팀 업무보고 채널 연결을 확인하세요.")
    room = chat_request("GET", "groups.info", headers=headers,
                        params={"roomId": target["room_id"]})["group"]
    if (room.get("_id") != target["room_id"] or room.get("t") != "p"
            or room.get("encrypted") or room.get("teamId") != settings.get("team_id")):
        raise HTTPException(403, "기술지원팀 보고방 구성을 확인하세요.")
    offset = 0
    while True:
        page = chat_request("GET", "groups.members", headers=headers, params={
            "roomId": target["room_id"], "count": 100, "offset": offset,
        })
        members = page.get("members", [])
        if any(member.get("_id") == user["_id"] and member.get("username") == user["username"]
               for member in members):
            return {**target, "name": room.get("fname") or room["name"]}
        offset += len(members)
        if not members or offset >= page.get("total", offset):
            raise HTTPException(403, "기술지원팀 업무보고 채널 구성원만 사용할 수 있습니다.")


def require_source_room(user, headers, room_id=None, *, legacy=False):
    """Resolve the configured two-member private report room (or old DM)."""
    settings = config()
    if legacy:
        selected = room_id or settings.get("legacy_room_id")
        if not selected:
            raise HTTPException(403, "이전 테스트방 연결을 확인하세요.")
        room = chat_request("GET", "groups.info", headers=headers,
                            params={"roomId": selected})["group"]
        if room.get("t") != "p" or room.get("encrypted"):
            raise HTTPException(403, "이전 테스트방 구성을 확인하세요.")
        return {"room_id": selected, "room_name": room.get("name", "이전 테스트방"),
                "room_type": "p"}
    own = (settings.get("personal_rooms", {}).get(user["username"])
           or settings.get("legacy_personal_rooms", {}).get(user["username"]))
    if own and (room_id is None or room_id == own["room_id"]):
        selected = own["room_id"]
        room = chat_request("GET", "groups.info", headers=headers,
                            params={"roomId": selected})["group"]
        members = chat_request("GET", "groups.members", headers=headers,
                               params={"roomId": selected, "count": 3})
        if room.get("t") != "p" or room.get("encrypted") or not private_members_ok(
                members, user["username"], settings["username"]):
            raise HTTPException(403, "개인보고 방은 본인과 report-bot만 참여해야 합니다.")
        return {"room_id": selected, "room_name": room.get("name", own.get("name")),
                "room_type": "p"}
    if room_id is None and settings.get("dm_mode"):
        created = chat_request("POST", "im.create", headers=headers,
                               body={"username": settings["username"]})
        direct = created.get("room", {})
        room_id = direct.get("rid") or direct.get("_id")
    if room_id is None:
        raise HTTPException(403, "이 계정의 개인보고 방이 아직 생성되지 않았습니다. 관리자에게 직원 동기화를 요청하세요.")
    members = chat_request("GET", "im.members", headers=headers,
                           params={"roomId": room_id, "count": 3})
    if not private_members_ok(members, user["username"], settings["username"]):
        raise HTTPException(403, "report-bot과 본인의 1:1 대화만 보고에 사용할 수 있습니다.")
    return {"room_id": room_id, "room_name": settings["username"], "room_type": "d"}


def resolve_user(x_rocket_user: str, x_rocket_token: str, x_review_room: str = "personal"):
    cache_key = hashlib.sha256(f"{x_rocket_user}\0{x_rocket_token}\0{x_review_room}".encode()).hexdigest()
    now = time.monotonic()
    with AUTH_CACHE_LOCK:
        cached = AUTH_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1])
        for key, value in list(AUTH_CACHE.items()):
            if value[0] <= now:
                AUTH_CACHE.pop(key, None)
    app_session = x_rocket_token.startswith("app:")
    if app_session:
        try:
            claim = verify_session(x_rocket_token[4:])
        except (ValueError, TypeError, json.JSONDecodeError):
            raise HTTPException(401, "자동 로그인 링크가 만료되었습니다. 개인보고 방에서 다시 열어 주세요.")
        if claim["user"] != x_rocket_user:
            raise HTTPException(401, "자동 로그인 계정을 확인하세요.")
        user = {"_id": claim["user"], "username": claim["username"]}
        headers = bot_headers()
        require_team_member(user, headers)
        source = require_source_room(user, headers, claim["room"])
    else:
        headers = {"X-User-Id": x_rocket_user, "X-Auth-Token": x_rocket_token}
        user = chat_request("GET", "me", headers=headers)
        if user.get("_id") != x_rocket_user:
            raise HTTPException(403, "Rocket.Chat 계정을 확인하세요.")
        require_team_member(user, headers)
        source = require_source_room(user, headers, legacy=x_review_room == "legacy")
    result = {"_id": user["_id"], "username": user["username"], **source,
              "private_mode": True, "app_session": app_session}
    with AUTH_CACHE_LOCK:
        AUTH_CACHE[cache_key] = (now + AUTH_CACHE_SECONDS, result)
    return result


def current_user(x_rocket_user: str = Header(), x_rocket_token: str = Header(), x_review_room: str = Header(default="personal")):
    return resolve_user(x_rocket_user, x_rocket_token, x_review_room)


def current_manager(x_rocket_user: str = Header(), x_rocket_token: str = Header()):
    if x_rocket_token.startswith("app:"):
        try:
            claim = verify_session(x_rocket_token[4:], purpose="team-session")
        except (ValueError, TypeError, json.JSONDecodeError):
            raise HTTPException(401, "업무 현황 자동 로그인이 만료되었습니다.")
        if claim["user"] != x_rocket_user:
            raise HTTPException(401, "업무 현황 계정을 확인하세요.")
        user = {"_id": claim["user"], "username": claim["username"], "roles": []}
        headers = bot_headers()
    else:
        headers = {"X-User-Id": x_rocket_user, "X-Auth-Token": x_rocket_token}
        user = chat_request("GET", "me", headers=headers)
        if user.get("_id") != x_rocket_user:
            raise HTTPException(403, "Rocket.Chat 계정을 확인하세요.")
    target = require_team_member(user, headers)
    return {"_id": user["_id"], "username": user["username"], "roles": user.get("roles", []),
            "room_id": target["room_id"], "room_name": target["name"]}


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr


class LinkLogin(BaseModel):
    token: str = Field(min_length=20, max_length=1200)


class ManagerQuestion(BaseModel):
    message: str = Field(min_length=1, max_length=200)


@app.middleware("http")
async def secure_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get("/health")
def health():
    return {"status": "ok", "mode": "local-chat-review"}


@app.post("/api/review/login")
def login(payload: Login):
    data = chat_request("POST", "login", body={"user": payload.username, "password": payload.password.get_secret_value()})["data"]
    resolve_user(data["userId"], data["authToken"])
    return {"user_id": data["userId"], "token": data["authToken"], "username": payload.username}


@app.post("/api/review/manager-login")
def manager_login(payload: Login):
    """Sign in a team member without requiring a personal report room."""
    data = chat_request("POST", "login", body={
        "user": payload.username,
        "password": payload.password.get_secret_value(),
    })["data"]
    headers = {"X-User-Id": data["userId"], "X-Auth-Token": data["authToken"]}
    require_team_member({"_id": data["userId"], "username": payload.username}, headers)
    return {"user_id": data["userId"], "token": data["authToken"], "username": payload.username}


@app.post("/api/review/link-login")
def link_login(payload: LinkLogin, db: Session = Depends(get_db)):
    try:
        claim = verify_link(payload.token)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "수정 링크가 만료되었거나 올바르지 않습니다. 개인보고 방에서 새 보고를 열어 주세요.")
    entity = db.get(ChatDraft, claim["draft"])
    if (not entity or entity.author_id != claim["user"] or entity.room_id != claim["room"]
            or not entity.author_username):
        raise HTTPException(401, "본인의 유효한 보고 수정 링크만 사용할 수 있습니다.")
    user = {"_id": entity.author_id, "username": entity.author_username}
    headers = bot_headers()
    require_team_member(user, headers)
    require_source_room(user, headers, entity.room_id)
    token = "app:" + issue_session(entity.author_id, entity.author_username, entity.room_id)
    return {"user_id": entity.author_id, "token": token, "username": entity.author_username,
            "draft_id": entity.id}


@app.post("/api/review/manager-link-login")
def manager_link_login(payload: LinkLogin):
    try:
        claim = verify_manager_link(payload.token)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "업무 현황 링크가 만료되었습니다. Rocket.Chat 업무보고 방에서 질문을 다시 입력해 주세요.")
    user = {"_id": claim["user"], "username": claim["username"]}
    target = require_team_member(user, bot_headers())
    token = "app:" + issue_session(claim["user"], claim["username"], target["room_id"],
                                    purpose="team-session")
    return {"user_id": claim["user"], "token": token, "username": claim["username"]}


@app.get("/api/review/manager/dashboard")
def manager_dashboard(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    project: str | None = Query(default=None, max_length=100),
    employee: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=30),
    db: Session = Depends(get_db),
    manager=Depends(current_manager),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "시작일은 종료일보다 늦을 수 없습니다.")
    if status and status not in {"DONE", "IN_PROGRESS", "NOT_STARTED", "DELAYED", "UNKNOWN"}:
        raise HTTPException(422, "업무 상태 필터를 확인하세요.")
    return get_manager_dashboard(
        db, date_from=date_from, date_to=date_to, project=project,
        employee=employee, status=status,
    )


@app.post("/api/review/manager/question")
def manager_question(payload: ManagerQuestion, db: Session = Depends(get_db), manager=Depends(current_manager)):
    answer, sources = answer_manager_question(get_manager_dashboard(db), payload.message)
    return {"answer": answer, "sources": sources}


@app.get("/api/review/drafts")
def drafts(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(ChatDraft).where(ChatDraft.author_id == user["_id"], ChatDraft.room_id == user["room_id"])
                      .order_by(ChatDraft.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "state": row.state, "submitted_at": row.submitted_at.isoformat(),
             "title": json.loads(row.current_data)[0]["task"]} for row in rows]


@app.get("/api/review/context")
def context(user=Depends(current_user)):
    return {"private_mode": user.get("private_mode", False), "room": user.get("room_name", "poc-reports"),
            "projects": PROJECTS, "report_room": config().get("channels", {}).get("reports", {}).get("name"),
            "chat_url": room_url({"name": user.get("room_name", "report-bot"),
                                  "type": user.get("room_type")})}


@app.get("/api/review/search")
def search(q: str = Query(default="오늘 보고", max_length=200), db: Session = Depends(get_db), user=Depends(current_user)):
    try:
        query = parse_query(q)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return search_reports(db, user["_id"], user["room_id"], query, limit=20)


@app.get("/api/review/drafts/{draft_id}")
def detail(draft_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize(db, owned_draft(db, draft_id, user))


@app.get("/api/review/imports/room")
def import_room(user=Depends(current_user)):
    return {"id": user["room_id"], "name": user.get("room_name", "poc-reports"), "scope": "선택한 방의 본인 메시지만"}


@app.post("/api/review/imports/preview")
def import_preview(payload: PreviewInput, db: Session = Depends(get_db), user=Depends(current_user),
                   x_rocket_user: str = Header(), x_rocket_token: str = Header()):
    headers = bot_headers() if x_rocket_token.startswith("app:") else {
        "X-User-Id": x_rocket_user, "X-Auth-Token": x_rocket_token}
    return preview_messages(db, user, payload, lambda endpoint, params: chat_request("GET", endpoint, headers=headers, params=params))


@app.post("/api/review/imports/draft")
def import_draft(payload: ImportInput, db: Session = Depends(get_db), user=Depends(current_user),
                 x_rocket_user: str = Header(), x_rocket_token: str = Header(), x_review_room: str = Header(default="personal")):
    headers = bot_headers() if x_rocket_token.startswith("app:") else {
        "X-User-Id": x_rocket_user, "X-Auth-Token": x_rocket_token}
    provider = DraftProvider()
    try:
        return import_message(db, user, payload, lambda endpoint, params: chat_request("GET", endpoint, headers=headers, params=params),
            lambda raw: asyncio.run(provider.parse_draft(raw)), provider.model,
            lambda: current_user(x_rocket_user, x_rocket_token, x_review_room))
    except LocalLLMError as exc:
        raise HTTPException(502, "Gemma 구조화에 실패했습니다. 이 메시지는 저장하지 않았습니다. 다시 시도하세요.") from exc


@app.put("/api/review/drafts/{draft_id}")
def edit(draft_id: str, payload: ReviewEdit, db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize(db, save_review(db, owned_draft(db, draft_id, user), user, payload, False))


@app.post("/api/review/drafts/{draft_id}/confirm")
def confirm(draft_id: str, payload: ReviewEdit, db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize(db, save_review(db, owned_draft(db, draft_id, user), user, payload, True))


def publish_target(user, headers):
    require_source_room(user, headers, user["room_id"])
    return require_team_member(user, headers)


@app.get("/api/review/drafts/{draft_id}/publication-preview")
def preview_publication(draft_id: str, db: Session = Depends(get_db), user=Depends(current_user),
                        x_rocket_user: str = Header(), x_rocket_token: str = Header()):
    headers = bot_headers() if x_rocket_token.startswith("app:") else {
        "X-User-Id": x_rocket_user, "X-Auth-Token": x_rocket_token}
    target = publish_target(user, headers)
    return publication_preview(db, owned_draft(db, draft_id, user), target)


@app.post("/api/review/drafts/{draft_id}/publish")
def publish_report(draft_id: str, payload: PublishInput, db: Session = Depends(get_db), user=Depends(current_user),
                   x_rocket_user: str = Header(), x_rocket_token: str = Header()):
    headers = bot_headers() if x_rocket_token.startswith("app:") else {
        "X-User-Id": x_rocket_user, "X-Auth-Token": x_rocket_token}
    target = config().get("channels", {}).get("reports")
    if not target:
        raise HTTPException(403, "게시할 보고방이 설정되지 않았습니다.")
    def authorize():
        # current_user already validates this request's identity and private room;
        # re-check the shared destination around the durable reservation.
        publish_target(user, headers)
    def deliver(row):
        from .worker import ChatAPI
        api = ChatAPI({**config(), "url": CHAT_URL})
        try:
            from .delivery import deliver_publication
            deliver_publication(api, row)
        finally:
            api.client.close()
    return publish(db, draft_id, user, payload, target, authorize, deliver)


def _quick_publish_identity(db: Session, token: str):
    try:
        claim = verify_link(token)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "보고 링크가 만료되었거나 올바르지 않습니다. 개인보고 방에서 새 보고를 작성해 주세요.")
    entity = db.get(ChatDraft, claim["draft"])
    if (not entity or entity.author_id != claim["user"] or entity.room_id != claim["room"]
            or not entity.author_username):
        raise HTTPException(401, "본인의 유효한 보고 링크만 사용할 수 있습니다.")
    headers = bot_headers()
    user = {"_id": entity.author_id, "username": entity.author_username,
            "room_id": entity.room_id, "room_type": "d"}
    require_team_member(user, headers)
    personal_ids = {r["room_id"] for group in (
        config().get("personal_rooms", {}), config().get("legacy_personal_rooms", {}))
        for r in group.values()}
    if entity.room_id in personal_ids:
        user["room_type"] = "p"
    require_source_room(user, headers, entity.room_id)
    return entity, user, headers


@app.post("/api/review/quick-publish")
def quick_publish(payload: LinkLogin, db: Session = Depends(get_db)):
    """Confirm the exact preview shown in a private room and publish it once."""
    entity, user, headers = _quick_publish_identity(db, payload.token)
    sent = db.scalar(select(ChatPublication).where(
        ChatPublication.draft_id == entity.id,
        ChatPublication.state == "SENT",
    ).order_by(ChatPublication.version.desc()))
    if sent:
        return {**receipt(sent), "already_sent": True}

    visible = db.scalar(select(ChatDraftRevision).where(
        ChatDraftRevision.draft_id == entity.id,
        ChatDraftRevision.action == "CHAT_PREVIEW",
    ).order_by(ChatDraftRevision.id.desc()))
    quick_confirm = db.scalar(select(ChatDraftRevision).where(
        ChatDraftRevision.draft_id == entity.id,
        ChatDraftRevision.version == entity.version,
        ChatDraftRevision.action == "CONFIRM",
        ChatDraftRevision.reason == "개인방 미리보기 원클릭 보고",
    ).order_by(ChatDraftRevision.id.desc()))
    if not visible:
        raise HTTPException(409, "개인보고 방에 실제로 표시된 보고만 게시할 수 있습니다.")
    if entity.state == "DRAFT" and entity.version == 1 and entity.current_data == visible.after_data:
        items = json.loads(entity.current_data)
        if any(item.get("project") not in PROJECTS or item.get("status") == "UNKNOWN" for item in items):
            raise HTTPException(422, "프로젝트와 상태를 수정 화면에서 확인한 뒤 게시해 주세요.")
        entity = save_review(db, entity, user, ReviewEdit(
            version=1,
            items=items,
            reason="개인방 미리보기 원클릭 보고",
        ), True)
    elif entity.state != "CONFIRMED" or not quick_confirm:
        raise HTTPException(409, "보고 내용이 수정되었습니다. 수정 화면에서 최신 내용을 확인하고 게시해 주세요.")

    target = config().get("channels", {}).get("reports")
    if not target:
        raise HTTPException(403, "게시할 보고방이 설정되지 않았습니다.")

    def authorize():
        publish_target(user, headers)

    def deliver(row):
        from .worker import ChatAPI
        from .delivery import deliver_publication
        api = ChatAPI({**config(), "url": CHAT_URL})
        try:
            deliver_publication(api, row)
        finally:
            api.client.close()

    view = publication_preview(db, entity, target)
    return publish(db, entity.id, user, PublishInput(
        version=entity.version,
        preview_hash=view["preview_hash"],
    ), target, authorize, deliver)


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn
    (LOCAL / "review.pid").write_text(str(os.getpid()), encoding="ascii")
    uvicorn.run(app, host="127.0.0.1", port=8003, access_log=False)
