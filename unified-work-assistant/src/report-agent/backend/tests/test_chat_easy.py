import hashlib
import json
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from contextlib import nullcontext

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import ChatDraftRevision, Report
from app.rocketchat.commands import command_for, confirm_from_chat
from app.rocketchat.query import ReportQuery, format_results, parse_query, search_reports
from app.rocketchat.review_app import app, current_user
from app.database import get_db
from app.rocketchat.worker import (ChatAPI, Worker, ensure_personal_rooms, list_direct_rooms,
                                   list_personal_rooms, persist_personal_rooms,
                                   report_team_members, response_retry_delay, retry_delay)
from test_chat_review import db, USER, count, edit, make_draft, save_review


def message(text="확정", identity="confirm1", **changes):
    return {"_id": identity, "rid": "room1", "u": {"_id": "employee1", "username": "poc-employee"},
            "ts": datetime.now(timezone.utc).isoformat(), "msg": text, **changes}


def test_direct_room_discovery_accepts_only_report_channel_members():
    responses = {
        "groups.members": {"members": [
            {"_id": "employee1", "username": "poc-employee"},
            {"_id": "bot1", "username": "report-bot"},
        ], "total": 2},
        "im.list": {"ims": [
            {"_id": "dm1", "t": "d", "usernames": ["report-bot", "poc-employee"],
             "uids": ["bot1", "employee1"]},
            {"_id": "dm2", "t": "d", "usernames": ["report-bot", "outsider"],
             "uids": ["bot1", "outside"]},
        ], "total": 2},
    }
    api = SimpleNamespace(call=lambda method, endpoint, **kwargs: responses[endpoint])
    cfg = {"username": "report-bot", "channels": {"reports": {"room_id": "reports"}}}
    allowed = report_team_members(api, cfg)
    assert allowed == {"poc-employee": "employee1"}
    assert list_direct_rooms(api, "report-bot", allowed) == [
        {"room_id": "dm1", "owner": "poc-employee"},
    ]


def test_personal_room_discovery_accepts_only_named_report_channel_members():
    api = SimpleNamespace(call=lambda method, endpoint, **kwargs: {"groups": [
        {"_id": "private1", "t": "p", "name": "개인보고-poc-employee"},
        {"_id": "project", "t": "p", "name": "AI업무비서-project"},
        {"_id": "outside", "t": "p", "name": "개인보고-outsider"},
    ], "total": 3})
    assert list_personal_rooms(api, "report-bot", {"poc-employee": "employee1"}) == [{
        "room_id": "private1", "owner": "poc-employee",
        "name": "개인보고-poc-employee", "type": "p",
    }]


def test_missing_team_member_gets_personal_room_automatically():
    calls = []
    def call(method, endpoint, body=None, params=None):
        calls.append((method, endpoint, body))
        if endpoint == "groups.list":
            return {"groups": [], "total": 0}
        if endpoint == "groups.create":
            assert body == {"name": "개인보고-new-employee", "members": ["new-employee"]}
            return {"group": {"_id": "new-room", "name": body["name"]}}
        if endpoint == "groups.members":
            return {"members": [{"username": "new-employee"}, {"username": "report-bot"}], "total": 2}
        return {"success": True}
    api = SimpleNamespace(call=call)
    rooms = ensure_personal_rooms(api, {
        "username": "report-bot", "personal_room_excluded_usernames": ["poc-admin"],
    }, {"new-employee": "new-id", "poc-admin": "admin-id"})
    assert rooms == [{"room_id": "new-room", "owner": "new-employee",
                      "name": "개인보고-new-employee", "type": "p"}]
    assert sum(endpoint == "groups.create" for _, endpoint, _ in calls) == 1


def test_excluded_existing_personal_room_is_not_subscribed():
    def call(method, endpoint, body=None, params=None):
        if endpoint == "groups.list":
            return {"groups": [
                {"_id": "employee-room", "name": "개인보고-employee", "t": "p"},
                {"_id": "admin-room", "name": "개인보고-poc-admin", "t": "p"},
            ], "total": 2}
        raise AssertionError(f"unexpected endpoint: {endpoint}")
    rooms = ensure_personal_rooms(SimpleNamespace(call=call), {
        "username": "report-bot", "personal_room_excluded_usernames": ["poc-admin"],
    }, {"employee": "employee-id", "poc-admin": "admin-id"})
    assert [room["owner"] for room in rooms] == ["employee"]


def test_personal_room_mapping_is_persisted_atomically(tmp_path, monkeypatch):
    from app.rocketchat import worker as worker_module
    (tmp_path / "bot.json").write_text(json.dumps({"username": "report-bot"}), encoding="utf-8")
    monkeypatch.setattr(worker_module, "LOCAL", tmp_path)
    cfg = {"personal_rooms": {}}
    rooms = [{"room_id": "room1", "owner": "employee", "name": "개인보고-employee", "type": "p"}]
    persist_personal_rooms(cfg, rooms)
    saved = json.loads((tmp_path / "bot.json").read_text(encoding="utf-8"))
    assert saved["personal_rooms"]["employee"]["room_id"] == "room1"
    assert saved["dm_mode"] is False


@pytest.mark.parametrize("text,kind", [("보고 화면을 수정 중입니다", "report"), ("!보고 자료조사 완료", "report"),
    ("확정", "confirm"), ("도움말", "help"), ("오늘 보고", "query"), ("이번 주 보고", "query"),
    ("미완료 보고", "query"), ("조회 2026-09-01~2026-09-08 화면", "query"), ("점심 먹었어요", None)])
def test_simple_commands(text, kind):
    result = command_for(message(text), "room1", {"poc-employee"}, "bot")
    assert (result[0] if result else None) == kind


@pytest.mark.parametrize("change", [{"rid": "other"}, {"u": {"_id": "bot", "username": "poc-employee"}},
    {"u": {"_id": "attacker", "username": "other"}}, {"t": "system"}, {"tmid": "parent"}])
def test_commands_do_not_capture_unrelated_messages(change):
    assert command_for(message("보고 테스트 완료", **change), "room1", {"poc-employee"}, "bot") is None


@pytest.mark.parametrize("text,start,end,keyword,incomplete", [
    ("오늘 보고", "2026-09-08", "2026-09-08", "", False),
    ("어제 보고", "2026-09-07", "2026-09-07", "", False),
    ("조회 이번 주 공간정보", "2026-09-07", "2026-09-08", "공간정보", False),
    ("지난 주 보고", "2026-08-31", "2026-09-06", "", False),
    ("미완료 보고", "2026-08-10", "2026-09-08", "", True),
    ("조회 2026-09-01~2026-09-03 화면", "2026-09-01", "2026-09-03", "화면", False),
    ("내가 오늘 보고한 내용 보여줘", "2026-09-08", "2026-09-08", "", False),
])
def test_query_dates(text, start, end, keyword, incomplete):
    q = parse_query(text, date(2026, 9, 8))
    assert (q.start.isoformat(), q.end.isoformat(), q.keyword, q.incomplete) == (start, end, keyword, incomplete)


@pytest.mark.parametrize("text", ["전체 직원 보고", "팀원 보고", "조회 2026-02-30", "조회 2026-09-08~2026-09-01",
    "조회 2024-01-01~2026-09-01", "조회 이번 달", "조회 9999-12-31", "조회 " + "가"*81])
def test_query_invalid_or_unsupported(text):
    with pytest.raises(ValueError):
        parse_query(text, date(2026, 9, 8))


def test_week_crosses_year():
    q = parse_query("이번 주 보고", date(2026, 1, 1))
    assert q.start == date(2025, 12, 29)


@pytest.mark.parametrize("status", ["DONE", "IN_PROGRESS", "NOT_STARTED", "DELAYED", "UNKNOWN"])
@pytest.mark.parametrize("progress", [None, 40])
def test_query_progress_visible_only_in_progress(status, progress):
    result = format_results({"start": "2026-09-09", "end": "2026-09-09", "incomplete": False,
        "keyword": "", "has_more": False, "items": [{"task": "화면 수정", "status": status,
        "progress": progress, "author": "테스트", "reported_at": "2026-09-09T09:00:00",
        "report_id": 1, "next_action": "", "issue": "", "source_url": "http://localhost/source",
        "review_url": "http://localhost/review"}]})
    assert ("진행률 미기재" in result) == (status == "IN_PROGRESS" and progress is None)
    assert ("40%" in result) == (status == "IN_PROGRESS" and progress == 40)


def test_own_confirmed_search_is_read_only_and_cites_sources(db):
    draft = make_draft(db)
    q = parse_query("오늘 보고")
    assert not search_reports(db, USER["_id"], "room1", q)["items"]
    save_review(db, draft, USER, edit(draft), True)
    counts = count(db, Report), count(db, ChatDraftRevision)
    result = search_reports(db, USER["_id"], "room1", q)
    assert len(result["items"]) == 2 and result["llm_used"] is False
    assert all(x["progress"] is None and draft.message_id in x["source_url"] and draft.id in x["review_url"] for x in result["items"])
    assert not search_reports(db, "other", "room1", q)["items"]
    assert not search_reports(db, USER["_id"], "other", q)["items"]
    assert len(search_reports(db, USER["_id"], "room1", parse_query("미완료 보고"))["items"]) == 1
    assert len(search_reports(db, USER["_id"], "room1", parse_query("조회 오늘 화면"))["items"]) == 1
    assert not search_reports(db, USER["_id"], "room1", parse_query("조회 오늘 %_"))["items"]
    limited = search_reports(db, USER["_id"], "room1", q, limit=1)
    assert limited["has_more"] and len(limited["items"]) == 1
    assert "원문 보기" in format_results(limited) and "진행률 미기재" in format_results(limited)
    assert counts == (count(db, Report), count(db, ChatDraftRevision))
    for report in db.scalars(select(Report)):
        report.created_at = datetime.combine(q.start - timedelta(days=1), datetime.min.time())
    db.commit()
    assert not search_reports(db, USER["_id"], "room1", q)["items"]


def test_confirm_single_and_retry_does_not_confirm_new_draft(db):
    draft = make_draft(db)
    request = message()
    assert "보고 확정 완료" in confirm_from_chat(db, request)
    assert count(db, Report) == 2
    other = make_draft(db, "source2", "다른 합성 보고")
    assert "이미 처리한" in confirm_from_chat(db, request)
    assert other.state == "DRAFT" and count(db, Report) == 2


@pytest.mark.parametrize("bot_reply", [False, True])
def test_ambiguous_confirm_requires_explicit_thread(db, bot_reply):
    draft = make_draft(db)
    make_draft(db, "source2", "다른 합성 보고")
    assert "여러 개" in confirm_from_chat(db, message()) and count(db, Report) == 0
    parent = "draft" + hashlib.sha256(f"room1:{draft.message_id}".encode()).hexdigest()[:24] if bot_reply else draft.message_id
    assert "보고 확정 완료" in confirm_from_chat(db, message(tmid=parent))
    assert count(db, Report) == 2


@pytest.mark.parametrize("changes", [{"u": {"_id": "other", "username": "other"}}, {"rid": "other"}])
def test_chat_confirmation_respects_ownership(db, changes):
    draft = make_draft(db)
    assert "초안이 없어요" in confirm_from_chat(db, message(tmid=draft.message_id, **changes))
    assert count(db, Report) == 0


def test_chat_confirmation_blocks_early_unknown_and_edited(db):
    draft = make_draft(db)
    assert "만들기 전에" in confirm_from_chat(db, message(ts="2000-01-01T00:00:00Z"))
    items = json.loads(draft.current_data)
    items[0]["status"] = "UNKNOWN"
    draft.current_data = json.dumps(items)
    db.commit()
    assert "상태 확인 필요" in confirm_from_chat(db, message())
    db.refresh(draft)
    save_review(db, draft, USER, edit(draft), False)
    assert "웹에서 수정한" in confirm_from_chat(db, message())
    assert count(db, Report) == 0


def test_short_code_selects_only_the_requested_own_draft(db):
    draft = make_draft(db)
    other = make_draft(db, "source2", "다른 합성 보고")
    request = message("확정 " + draft.id[:8])
    assert command_for(request, "room1", {"poc-employee"}, "bot")[0] == "confirm"
    assert "초안이 없어요" in confirm_from_chat(db, {**request, "u": {"_id": "other", "username": "other"}})
    assert "보고 확정 완료" in confirm_from_chat(db, request)
    assert other.state == "DRAFT" and count(db, Report) == 2


def test_search_endpoint_auth_scope_and_no_llm(db, monkeypatch):
    draft = make_draft(db)
    save_review(db, draft, USER, edit(draft), True)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: USER
    try:
        with TestClient(app) as client:
            response = client.get("/api/review/search", params={"q": "오늘 보고"})
            assert response.status_code == 200 and len(response.json()["items"]) == 2
            assert client.get("/api/review/search", params={"q": "팀원 보고"}).status_code == 422
            app.dependency_overrides[current_user] = lambda: {**USER, "_id": "other"}
            assert client.get("/api/review/search").json()["items"] == []
    finally:
        app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.get("/api/review/search").status_code == 422
    worker = Worker.__new__(Worker)
    worker.room = "room1"
    worker.config = {"allowed_usernames": ["poc-employee"]}
    worker.api = SimpleNamespace(user_id="bot")
    worker.provider = None  # Query must never call model parsing.
    monkeypatch.setattr("app.rocketchat.worker.SessionLocal", lambda: nullcontext(db))
    assert "내 확정 보고 조회" in worker.respond(message("오늘 보고"), 0)


def test_long_chat_results_stay_within_message_limit():
    row = {"report_id": 1, "task": "*"*160, "status": "IN_PROGRESS", "progress": None,
        "next_action": "*"*240, "issue": "*"*1000, "author": "*"*60,
        "reported_at": "2026-09-08T09:00:00", "source_url": "http://127.0.0.1:3000/group/poc-reports?msg="+"a"*30,
        "review_url": "http://127.0.0.1:8003/#"+"a"*64}
    result = {"start": "2026-09-08", "end": "2026-09-08", "keyword": "", "incomplete": False,
        "items": [row]*5, "has_more": False}
    assert len(format_results(result)) <= 4800
    assert "최신" in format_results(result)


def test_worker_reuses_cached_result_after_delivery_failure(tmp_path):
    worker = Worker.__new__(Worker)
    worker.config = {}
    worker.db = sqlite3.connect(tmp_path / "queue.db")
    worker.db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY,payload TEXT,state TEXT,result TEXT)")
    worker.db.execute("INSERT INTO jobs VALUES (?,?,'pending',NULL)", ("c1", json.dumps(message(identity="c1"))))
    worker.db.commit()
    calls = []
    worker.ensure_placeholder = lambda _: "preview"
    worker.room = "room1"
    worker.respond = lambda *_: calls.append("respond") or "보고 확정 완료"
    def fail(*_, **__):
        raise httpx.ConnectError("synthetic delivery error")
    worker.api = SimpleNamespace(call=fail)
    with pytest.raises(httpx.ConnectError):
        worker.process_one()
    assert calls == ["respond"]
    worker.api.call = lambda *_: None
    assert worker.process_one()
    assert calls == ["respond"]
    assert worker.db.execute("SELECT state,payload,result FROM jobs").fetchone() == ("done", None, None)
    worker.db.close()


@pytest.mark.parametrize("header,expected", [("22", 22.0), ("1", 5.0), ("999", 120.0), ("invalid", 60.0)])
def test_worker_respects_rate_limit_retry_after(header, expected):
    request = httpx.Request("GET", "http://127.0.0.1/api/v1/groups.history")
    response = httpx.Response(429, request=request, headers={"Retry-After": header})
    error = httpx.HTTPStatusError("rate limited", request=request, response=response)
    assert retry_delay(error) == expected


def test_response_retry_delay_uses_retry_after():
    response = httpx.Response(429, headers={"Retry-After": "7"})
    assert response_retry_delay(response) == 7


def test_chat_api_remembers_an_exhausted_endpoint_window():
    class FakeClient:
        def request(self, *args, **kwargs):
            return httpx.Response(200, json={"success": True}, headers={
                "x-ratelimit-remaining": "0", "Retry-After": "7",
            }, request=httpx.Request("GET", "http://127.0.0.1/api/v1/groups.info"))

    api = ChatAPI.__new__(ChatAPI)
    api.client = FakeClient()
    api.rate_limit_until = {}
    before = time.monotonic()
    assert api.call("GET", "groups.info") == {"success": True}
    assert api.rate_limit_until["groups.info"] >= before + 6.5


def test_private_room_check_is_cached_for_one_processing_window():
    calls = []
    worker = Worker.__new__(Worker)
    worker.config = {"personal_owner": "poc-employee", "username": "report-bot"}
    worker.room = "room1"
    worker.private_room_verified_until = 0.0

    def call(method, endpoint, body=None, params=None):
        calls.append(endpoint)
        if endpoint == "groups.info":
            return {"group": {"_id": "room1", "t": "p", "encrypted": False}}
        return {"members": [
            {"username": "poc-employee"}, {"username": "report-bot"},
        ], "total": 2}

    worker.api = SimpleNamespace(call=call)
    worker.check_private_room()
    worker.check_private_room()
    assert calls == ["groups.info", "groups.members"]
