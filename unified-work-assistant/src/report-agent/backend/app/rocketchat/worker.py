"""One local worker, one allowlisted private room, explicitly triggered drafts only."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import queue
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .draft import DraftProvider, render_chat_draft
from ..llm.local import LocalLLMError
from ..database import SessionLocal
from ..models import ChatDraft
from .review_service import register_draft
from .commands import HELP, command_for, confirm_from_chat, manager_command_for, team_query_command_for
from .query import KST, format_results, parse_query, search_reports
from .workspace import private_members_ok
from .chat_publication import personal_preview, personal_actions, mark_displayed, publish_from_chat, authorize_chat_target
from .delivery import deliver_publication
from .link_auth import issue_link, issue_manager_link
from .manager_query import ManagerQueryProvider, fallback_manager_query
from .manager_service import (answer_structured_manager_query, format_structured_manager_answer,
                              manager_query_context)
from .realtime import RoomMessageStream, normalize_message
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

LOCAL = Path(os.getenv(
    "ROCKETCHAT_LOCAL_PATH",
    Path(__file__).resolve().parents[3] / "rocketchat" / ".local",
))
log = logging.getLogger("report_bot")
FALLBACK_POLL_SECONDS = max(120.0, float(os.getenv("ROCKETCHAT_FALLBACK_POLL_SECONDS", "300")))
IDLE_SECONDS = 0.25
ROOM_CHECK_CACHE_SECONDS = 60.0
DM_DISCOVERY_SECONDS = max(10.0, float(os.getenv("ROCKETCHAT_DM_DISCOVERY_SECONDS", "15")))
TEAM_MEMBERS_SECONDS = max(15.0, float(os.getenv("ROCKETCHAT_TEAM_MEMBERS_SECONDS", "30")))


def retry_delay(exc: Exception) -> float:
    """Respect Rocket.Chat's rate-limit window without logging message data."""
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code != 429:
        return 5.0
    retry_after = exc.response.headers.get("retry-after")
    if retry_after:
        try:
            return min(120.0, max(5.0, float(retry_after)))
        except ValueError:
            pass
    return 60.0


def response_retry_delay(response: httpx.Response) -> float:
    """Return a bounded wait using Rocket.Chat's standard limiter headers."""
    retry_after = response.headers.get("retry-after", "")
    try:
        if retry_after:
            return min(60.0, max(1.0, float(retry_after)))
    except ValueError:
        pass
    reset = response.headers.get("x-ratelimit-reset", "")
    try:
        value = float(reset)
        reset_seconds = value / 1000 if value > 10_000_000_000 else value
        return min(60.0, max(1.0, reset_seconds - time.time()))
    except ValueError:
        pass
    try:
        reset_at = datetime.fromisoformat(reset.replace("Z", "+00:00"))
        return min(60.0, max(1.0, reset_at.timestamp() - time.time()))
    except ValueError:
        return 10.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def report_body(message: dict, room_id: str, allowed: set[str], bot_id: str) -> str | None:
    user = message.get("u", {})
    if (message.get("rid") != room_id or user.get("_id") == bot_id
            or user.get("username") not in allowed or message.get("tmid") or message.get("t")):
        return None
    text = message.get("msg", "")
    if text == "!보고":
        return ""
    if not text.startswith("!보고") or len(text) < 4 or not text[3].isspace():
        return None
    return text[3:].strip()


class ChatAPI:
    def __init__(self, config: dict):
        allowed_hosts = {"127.0.0.1", "localhost"}
        internal_host = urlparse(os.getenv("ROCKETCHAT_INTERNAL_URL", "")).hostname
        if internal_host:
            allowed_hosts.add(internal_host)
        if urlparse(config["url"]).hostname not in allowed_hosts:
            raise ValueError("이 개발용 봇은 로컬 Rocket.Chat에서만 실행할 수 있습니다.")
        self.config = config
        self.client = httpx.Client(base_url=config["url"], timeout=30, trust_env=False)
        self.rate_limit_until = {}
        self.login()

    def login(self):
        for attempt in range(6):
            response = self.client.post("/api/v1/login", json={
                "user": self.config["username"], "password": self.config["password"],
            })
            if response.status_code != 429 or attempt == 5:
                break
            retry_after = response.headers.get("retry-after", "")
            delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 10.0
            time.sleep(max(1.0, min(delay, 30.0)))
        response.raise_for_status()
        data = response.json()["data"]
        self.user_id = data["userId"]
        self.client.headers.update({"X-User-Id": self.user_id, "X-Auth-Token": data["authToken"]})

    def call(self, method, endpoint, body=None, params=None):
        authenticated_again = False
        for attempt in range(7):
            delay = self.rate_limit_until.get(endpoint, 0.0) - time.monotonic()
            if delay > 0:
                log.info("rate_window_wait endpoint=%s seconds=%s", endpoint, int(delay))
                time.sleep(min(60.0, delay))
            response = self.client.request(method, "/api/v1/" + endpoint, json=body, params=params)
            if response.status_code == 401 and not authenticated_again:
                self.login()
                authenticated_again = True
                continue
            if response.status_code != 429 or attempt == 6:
                break
            delay = response_retry_delay(response)
            self.rate_limit_until[endpoint] = time.monotonic() + delay
            log.warning("rate_limited endpoint=%s retry_seconds=%s", endpoint, int(delay))
            time.sleep(delay)
        response.raise_for_status()
        if response.headers.get("x-ratelimit-remaining") == "0":
            self.rate_limit_until[endpoint] = time.monotonic() + response_retry_delay(response)
        result = response.json()
        if result.get("success") is False:
            raise RuntimeError(f"Rocket.Chat {endpoint} failed")
        return result


class Worker:
    def __init__(self, config: dict, state_path: Path, api: ChatAPI | None = None):
        self.config = config
        # Every room uses the same bot account. Sharing one authenticated client
        # avoids one login request per employee when the worker starts.
        self.api = api or ChatAPI(config)
        self.room = config["room_id"]
        self.provider = DraftProvider()
        self.manager_provider = ManagerQueryProvider() if (
            config.get("manager_owner") or config.get("query_scope") == "team"
        ) else None
        self.private_room_verified_until = 0.0
        self.db = sqlite3.connect(state_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY, stamp TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT, state TEXT NOT NULL)")
        if "result" not in {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}:
            self.db.execute("ALTER TABLE jobs ADD COLUMN result TEXT")
        self.db.execute("INSERT OR IGNORE INTO cursor VALUES (1, ?)", (
            config.get("initial_cursor", utc_now()),
        ))
        self.db.commit()

    def detect_command(self, message: dict):
        if self.config.get("query_scope") == "team":
            return team_query_command_for(
                message, self.room, set(self.config["allowed_usernames"]), self.api.user_id)
        manager = self.config.get("manager_owner")
        if manager:
            return manager_command_for(message, self.room, manager, self.api.user_id)
        return command_for(message, self.room, set(self.config["allowed_usernames"]), self.api.user_id)

    def poll(self):
        start = self.db.execute("SELECT stamp FROM cursor WHERE id=1").fetchone()[0]
        end = utc_now()
        offset = 0
        collected = []
        while True:
            history_endpoint = "im.history" if self.config.get("room_type") == "d" else "groups.history"
            messages = self.api.call("GET", history_endpoint, params={
                "roomId": self.room, "oldest": start, "latest": end,
                "inclusive": "true", "count": 100, "offset": offset,
            })["messages"]
            collected.extend(messages)
            if len(messages) < 100:
                break
            offset += 100
        with self.db:
            for message in sorted(collected, key=lambda item: (item["ts"], item["_id"])):
                command = self.detect_command(message)
                if command is not None:
                    self.db.execute("INSERT OR IGNORE INTO jobs (id,payload,state) VALUES (?, ?, 'pending')", (
                        message["_id"], json.dumps(message, ensure_ascii=False),
                    ))
            self.db.execute("UPDATE cursor SET stamp=? WHERE id=1", (end,))

    def enqueue(self, message: dict) -> bool:
        """Queue a realtime message; the message ID makes reconnect delivery idempotent."""
        if self.detect_command(message) is None:
            return False
        with self.db:
            result = self.db.execute(
                "INSERT OR IGNORE INTO jobs (id,payload,state) VALUES (?, ?, 'pending')",
                (message["_id"], json.dumps(message, ensure_ascii=False)),
            )
        return result.rowcount == 1

    def reply_id(self, source_id: str) -> str:
        return "draft" + hashlib.sha256(f"{self.room}:{source_id}".encode()).hexdigest()[:24]

    def action_id(self, source_id: str) -> str:
        return "action" + hashlib.sha256(f"{self.room}:{source_id}".encode()).hexdigest()[:24]

    def upsert_action(self, message: dict, text: str):
        message_id = self.action_id(message["_id"])
        try:
            existing = self.api.call("GET", "chat.getMessage", params={"msgId": message_id})["message"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (400, 404):
                raise
            self.api.call("POST", "chat.sendMessage", {"message": {
                "_id": message_id, "rid": self.room, "msg": text,
            }, "previewUrls": []})
            return
        if existing["rid"] != self.room or existing["u"]["_id"] != self.api.user_id:
            raise RuntimeError("Unexpected action message ownership")
        self.api.call("POST", "chat.update", {"roomId": self.room, "msgId": message_id, "text": text})

    def ensure_placeholder(self, message: dict) -> str:
        reply_id = self.reply_id(message["_id"])
        try:
            existing = self.api.call("GET", "chat.getMessage", params={"msgId": reply_id})["message"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (400, 404):
                raise
        else:
            if existing["rid"] != self.room or existing["u"]["_id"] != self.api.user_id:
                raise RuntimeError("Unexpected reply ownership")
            return reply_id
        self.api.call("POST", "chat.sendMessage", {"message": {
            "_id": reply_id, "rid": self.room,
            **({"tmid": message["tmid"]} if message.get("tmid") else {}),
            "msg": "요청을 확인하고 있어요. 잠시만 기다려 주세요.",
        }, "previewUrls": []})
        return reply_id

    def process_one(self) -> bool:
        row = self.db.execute("SELECT id, payload, result FROM jobs WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
        if not row:
            return False
        source_id, payload, cached = row
        message = normalize_message(json.loads(payload))
        self.check_private_room()
        reply_id = self.ensure_placeholder(message)
        started = time.perf_counter()
        status = "done"
        try:
            text = cached if cached is not None else self.respond(message, started)
        except (LocalLLMError, ValueError, HTTPException, IntegrityError) as exc:
            status = "error"
            detail = exc.detail if isinstance(exc, HTTPException) else ("중복 또는 동시 수정 요청입니다. 기존 보고를 확인해 주세요." if isinstance(exc, IntegrityError) else str(exc))
            text = f"[요청 확인 필요]\n{detail}\n다시 안내가 필요하면 `도움말`이라고 입력해 주세요."
        with self.db:
            self.db.execute("UPDATE jobs SET result=? WHERE id=?", (text, source_id))
        self.check_private_room()
        self.api.call("POST", "chat.update", {"roomId": self.room, "msgId": reply_id, "text": text})
        if status == "done" and self.config.get("personal_owner"):
            command = self.detect_command(message)
            if command and command[0] == "report" and command[1]:
                with SessionLocal() as session:
                    draft_id = hashlib.sha256(
                        f"local-rocketchat:{self.room}:{message['_id']}".encode()).hexdigest()
                    entity = session.get(ChatDraft, draft_id)
                    if not entity:
                        raise RuntimeError("Draft missing after preview generation")
                    mark_displayed(session, message)
                    token = issue_link(entity)
                    review_base = os.getenv("REVIEW_PUBLIC_URL", "http://127.0.0.1:8003").rstrip("/")
                    review_url = f"{review_base}/?access={token}#{entity.id}"
                    publish_url = f"{review_base}/assets/quick-publish.html#{token}"
                    action_text = personal_actions(
                        entity, self.provider.model, time.perf_counter() - started,
                        review_url, publish_url,
                    )
                    self.upsert_action(message, action_text)
        with self.db:
            # Only retain IDs/status for deduplication; raw text remains in the source chat.
            self.db.execute("UPDATE jobs SET state=?, payload=NULL, result=NULL WHERE id=?", (status, source_id))
        log.info("draft_processed state=%s elapsed_seconds=%.1f", status, time.perf_counter() - started)
        return True

    def check_private_room(self):
        owner = self.config.get("personal_owner") or self.config.get("manager_owner")
        if owner:
            now = time.monotonic()
            if getattr(self, "private_room_verified_until", 0.0) > now:
                return
            if self.config.get("room_type") == "d":
                members = self.api.call("GET", "im.members", params={"roomId": self.room, "count": 3})
                if not private_members_ok(members, owner, self.config["username"]):
                    raise RuntimeError("Direct-message membership changed; processing paused")
            else:
                room = self.api.call("GET", "groups.info", params={"roomId": self.room})["group"]
                members = self.api.call("GET", "groups.members", params={"roomId": self.room, "count": 3})
                if room.get("t") != "p" or room.get("encrypted") or not private_members_ok(
                        members, owner, self.config["username"]):
                    raise RuntimeError("Personal room membership or encryption changed; processing paused")
            self.private_room_verified_until = now + ROOM_CHECK_CACHE_SECONDS

    def respond(self, message: dict, started: float) -> str:
        command = self.detect_command(message)
        if command is None:
            return "허용된 테스트방 요청만 처리합니다."
        kind, raw = command
        if kind in {"manager_help", "team_help"}:
            heading = "팀 업무 비서 사용법" if kind == "team_help" else "관리자 업무 비서 사용법"
            return (f"**{heading}**\n"
                    "`오늘 poc-employee 사원 보고 보여줘` · 직원별 당일 보고\n"
                    "`오늘 업무비서 프로젝트 보고 다 보여줘` · 프로젝트별 당일 보고\n"
                    "`공간정보 프로젝트 진행사항 알려줘` · 최신 프로젝트 현황\n"
                    "`확인할 리스크 알려줘` · 지연·이슈 조회\n\n"
                    "Gemma 3가 질문 조건을 해석하고, 답변은 확정 보고 DB만 조회합니다."
                    " 상세 목록은 전체 현황 화면에서 확인할 수 있습니다.")
        if kind in {"manager", "team_query"}:
            query_day = datetime.fromisoformat(message["ts"].replace("Z", "+00:00")).astimezone(KST).date()
            with SessionLocal() as db:
                employees = manager_query_context(db)
            llm_used = True
            try:
                query = asyncio.run(self.manager_provider.parse_question(raw, employees, query_day))
            except LocalLLMError:
                query = fallback_manager_query(raw, query_day)
                llm_used = False
            with SessionLocal() as db:
                answer, sources = answer_structured_manager_query(db, query, query_day)
            token = issue_manager_link(message["u"]["_id"], message["u"]["username"])
            review_base = os.getenv("REVIEW_PUBLIC_URL", "http://127.0.0.1:8003").rstrip("/")
            dashboard_url = f"{review_base}/assets/manager.html?access={token}"
            return format_structured_manager_answer(
                answer, sources, dashboard_url, self.manager_provider.model, llm_used,
                heading="팀 업무 비서" if kind == "team_query" else "관리자 업무 비서")
        if kind == "publish" and self.config.get("personal_owner"):
            authorized = False
            def authorize():
                nonlocal authorized
                if authorized:
                    return
                self.check_private_room()
                authorize_chat_target(self.api, self.config, message["u"], self.room)
                authorized = True
            with SessionLocal() as db:
                return publish_from_chat(db, message, self.config.get("channels", {}).get("reports"),
                                         authorize, lambda row: deliver_publication(self.api, row))
        if kind == "help" or kind == "publish" or (kind == "report" and not raw):
            if self.config.get("personal_owner"):
                return ("**개인보고 방 사용법**\n1. `보고 업무내용` 입력\n2. 보고 양식으로 나온 미리보기 확인"
                        "\n3. 맞으면 `✅ 이대로 보고` 클릭 → 팀 업무보고 방에 저장·게시"
                        "\n키보드로 하려면 `보고` 입력 후 Enter"
                        "\n고칠 때만 ‘내용 수정하기’ → 수정·저장 → 게시 미리보기 → 보고방에 게시"
                        "\n\n`오늘 보고` / `이번 주 보고`: 내 저장 보고 조회"
                        "\n개인 저장과 팀 공유는 별개입니다. 프로젝트방 대화는 자동 수집하지 않습니다.")
            return HELP
        if kind in {"query", "confirm"}:
            with SessionLocal() as db:
                if kind == "confirm":
                    if self.config.get("personal_owner"):
                        return "개인보고 방 미리보기가 맞으면 `보고`를 입력하면 팀 보고방에 게시됩니다. 수정이 필요하면 [수정 화면](http://127.0.0.1:8003)에서 수정·저장 후 게시하세요."
                    return confirm_from_chat(db, message)
                today = datetime.fromisoformat(message["ts"].replace("Z", "+00:00")).astimezone(KST).date()
                return format_results(search_reports(db, message["u"]["_id"], self.room, parse_query(raw, today), limit=5))
        if not 5 <= len(raw) <= 4000:
            raise ValueError("'보고' 뒤에 업무 내용을 5~4,000자로 입력해 주세요.")
        draft = asyncio.run(self.provider.parse_draft(raw))
        with SessionLocal() as db:
            saved = register_draft(db, message, raw, draft, self.provider.model)
            review_id = saved.id
            if self.config.get("personal_owner"):
                return personal_preview(saved, self.provider.model, time.perf_counter() - started)
        timestamp = datetime.fromisoformat(message["ts"].replace("Z", "+00:00"))
        rendered = render_chat_draft(draft, message["u"].get("name") or message["u"]["username"],
                                 timestamp, review_id, self.provider.model, time.perf_counter() - started)
        return rendered


def report_team_members(api: ChatAPI, config: dict) -> dict[str, str]:
    """Return username -> id for members allowed to use the report workflow."""
    target = config.get("channels", {}).get("reports")
    if not target:
        return {}
    offset = 0
    found = {}
    while True:
        result = api.call("GET", "groups.members", params={
            "roomId": target["room_id"], "count": 100, "offset": offset,
        })
        members = result.get("members", [])
        for member in members:
            username, user_id = member.get("username"), member.get("_id")
            if username and user_id and username != config["username"]:
                found[username] = user_id
        offset += len(members)
        if not members or offset >= result.get("total", offset):
            return found


def list_direct_rooms(api: ChatAPI, bot_username: str, allowed: dict[str, str]) -> list[dict]:
    """Discover only two-member DMs between report-bot and an allowed team member."""
    offset = 0
    found = []
    while True:
        result = api.call("GET", "im.list", params={"count": 100, "offset": offset})
        rooms = result.get("ims", [])
        for room in rooms:
            usernames = room.get("usernames") or room.get("_USERNAMES") or []
            uids = room.get("uids") or []
            if room.get("t") != "d" or len(usernames) != 2 or bot_username not in usernames:
                continue
            owner = next((name for name in usernames if name != bot_username), None)
            if owner not in allowed or allowed[owner] not in uids:
                continue
            found.append({"room_id": room["_id"], "owner": owner})
        offset += len(rooms)
        if not rooms or offset >= result.get("total", offset):
            return found


def list_personal_rooms(api: ChatAPI, bot_username: str, allowed: dict[str, str]) -> list[dict]:
    """Discover bot-owned two-member private rooms named for allowed employees."""
    offset = 0
    found = []
    while True:
        result = api.call("GET", "groups.list", params={"count": 100, "offset": offset})
        rooms = result.get("groups", [])
        for room in rooms:
            if room.get("t") != "p" or not room.get("name", "").startswith("개인보고-"):
                continue
            owner = room["name"][len("개인보고-"):]
            if owner not in allowed:
                continue
            found.append({"room_id": room["_id"], "owner": owner,
                          "name": room["name"], "type": "p"})
        offset += len(rooms)
        if not rooms or offset >= result.get("total", offset):
            return found


def ensure_personal_rooms(api: ChatAPI, config: dict, allowed: dict[str, str]) -> list[dict]:
    """Create missing employee report rooms with the bot as the room owner."""
    excluded = set(config.get("personal_room_excluded_usernames", [])) | {config["username"]}
    eligible = {username: user_id for username, user_id in allowed.items()
                if username not in excluded}
    rooms = list_personal_rooms(api, config["username"], eligible)
    existing = {room["owner"] for room in rooms}
    for owner in sorted(set(eligible) - existing):
        try:
            created = api.call("POST", "groups.create", {
                "name": f"개인보고-{owner}", "members": [owner],
            })["group"]
            api.call("POST", "groups.setTopic", {
                "roomId": created["_id"],
                "topic": "본인 + report-bot | 보고 업무내용 → AI 구조화 → 확인·수정 → 업무보고에 게시",
            })
        except httpx.HTTPStatusError as exc:
            # A conflicting room name or revoked create permission must not stop
            # existing employees' reports. The administrator can inspect logs.
            log.warning("personal_room_auto_create_failed status=%s", exc.response.status_code)
            continue
        room = {"room_id": created["_id"], "owner": owner,
                "name": created["name"], "type": "p"}
        members = api.call("GET", "groups.members", params={
            "roomId": room["room_id"], "count": 3,
        })
        if not private_members_ok(members, owner, config["username"]):
            raise RuntimeError("Automatically created personal room has unexpected members")
        rooms.append(room)
        log.info("Personal report room automatically created")
    return rooms


def persist_personal_rooms(config: dict, rooms: list[dict]) -> None:
    """Persist room mapping so review links work without restarting services."""
    mapping = {room["owner"]: {key: room[key] for key in ("room_id", "name", "type")}
               for room in rooms}
    if config.get("personal_rooms") == mapping:
        return
    config["personal_rooms"] = mapping
    path = LOCAL / "bot.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    current["personal_rooms"] = mapping
    current["dm_mode"] = False
    temporary = path.with_name(f"bot-{os.getpid()}.tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Keep a process-scoped lock so repeated start commands cannot run two workers.
    lock = (LOCAL / "worker.lock").open("a+b")
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except ImportError:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info("A local draft worker is already running.")
        return
    config = json.loads((LOCAL / "bot.json").read_text(encoding="utf-8"))
    config["url"] = os.getenv("ROCKETCHAT_INTERNAL_URL", config["url"]).rstrip("/")
    shared_api = ChatAPI(config)
    workers = [
        Worker(
            {**config, "room_id": room["room_id"], "room_type": "p",
             "allowed_usernames": [owner], "personal_owner": owner},
            LOCAL / ("worker-" + hashlib.sha256(room["room_id"].encode()).hexdigest()[:12] + ".sqlite3"),
            shared_api,
        )
        for owner, room in config.get("personal_rooms", {}).items()
    ]
    reports_room = config.get("channels", {}).get("reports")
    if reports_room:
        workers.append(Worker(
            {**config, "room_id": reports_room["room_id"], "query_scope": "team"},
            LOCAL / ("worker-team-query-" + hashlib.sha256(
                reports_room["room_id"].encode()).hexdigest()[:12] + ".sqlite3"),
            shared_api,
        ))
    if not workers and not config.get("dm_mode"):
        workers = [Worker(config, LOCAL / "worker.sqlite3", shared_api)]
    worker_by_room = {worker.room: worker for worker in workers}
    incoming = queue.SimpleQueue()
    stream = RoomMessageStream(
        config["url"], config["username"], config["password"], worker_by_room, incoming.put)
    stream.start()
    (LOCAL / "worker.pid").write_text(str(os.getpid()), encoding="ascii")
    log.info("Ready: %s fixed workers; dynamic report rooms; Gemma previews", len(workers))
    next_fallback_poll = time.monotonic()
    next_dm_discovery = 0.0
    next_team_members = 0.0
    team_members = {}
    while True:
        try:
            while True:
                try:
                    message = incoming.get_nowait()
                except queue.Empty:
                    break
                worker = worker_by_room.get(message.get("rid"))
                if worker:
                    worker.enqueue(message)
            now = time.monotonic()
            if now >= next_team_members:
                team_members = report_team_members(shared_api, config)
                config["allowed_usernames"] = sorted(team_members)
                if reports_room and reports_room["room_id"] in worker_by_room:
                    worker_by_room[reports_room["room_id"]].config["allowed_usernames"] = sorted(team_members)
                for worker in workers:
                    owner = worker.config.get("personal_owner")
                    if owner:
                        worker.config["allowed_usernames"] = [owner] if owner in team_members else []
                next_team_members = now + TEAM_MEMBERS_SECONDS
            if now >= next_dm_discovery:
                discovered = (list_direct_rooms(shared_api, config["username"], team_members)
                              if config.get("dm_mode") else
                              ensure_personal_rooms(shared_api, config, team_members))
                if not config.get("dm_mode"):
                    persist_personal_rooms(config, discovered)
                for room in discovered:
                    if room["room_id"] in worker_by_room:
                        continue
                    cursor = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(
                        timespec="milliseconds").replace("+00:00", "Z")
                    worker = Worker(
                        {**config,
                         "personal_rooms": {**config.get("personal_rooms", {}), room["owner"]: room},
                         "room_id": room["room_id"], "room_type": room.get("type", "p"),
                         "allowed_usernames": [room["owner"]], "personal_owner": room["owner"],
                         "initial_cursor": cursor},
                        LOCAL / (("worker-dm-" if room.get("type") == "d" else "worker-")
                                 + hashlib.sha256(room["room_id"].encode()).hexdigest()[:12] + ".sqlite3"),
                        shared_api,
                    )
                    worker.check_private_room()
                    worker_by_room[worker.room] = worker
                    workers.append(worker)
                    stream.add_room(worker.room)
                    worker.poll()
                    log.info("Authorized team personal-report worker added type=%s", room.get("type", "p"))
                next_dm_discovery = now + DM_DISCOVERY_SECONDS
            if now >= next_fallback_poll:
                for worker in workers:
                    worker.poll()
                next_fallback_poll = now + FALLBACK_POLL_SECONDS
            for worker in workers:
                worker.process_one()
        except (httpx.HTTPError, RuntimeError, KeyError) as exc:
            # Avoid raw reports and authentication details in logs.
            status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "n/a"
            delay = retry_delay(exc)
            log.warning("temporary_failure type=%s status=%s retry_seconds=%s",
                        type(exc).__name__, status_code, int(delay))
            time.sleep(delay)
        time.sleep(IDLE_SECONDS)


if __name__ == "__main__":
    main()
