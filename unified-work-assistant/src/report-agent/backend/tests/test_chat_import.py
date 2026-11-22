import copy
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.database import get_db
from app.llm.local import LocalLLMError
from app.models import ChatDraft, ChatDraftRevision, Report
from app.rocketchat.commands import confirm_from_chat
from app.rocketchat.draft import ReportDraft
from app.rocketchat.import_service import (IMPORT_SLOT, PreviewInput, ImportInput, boundaries,
    fingerprint, import_message, preview_messages)
from app.rocketchat.review_app import app, current_user
from app.rocketchat.review_service import save_review
from test_chat_review import USER, db, count, edit

SOURCE = {"_id": "old-source", "rid": "room1", "u": {"_id": "employee1", "username": "poc-employee"},
    "ts": "2026-09-07T04:00:00.000Z", "msg": "검색 화면 수정 작업은 진행 중입니다."}


def scope(**changes):
    return PreviewInput(room_id="room1", start=date(2026,9,7), end=date(2026,9,7), **changes)


def selection(source=None):
    source = source or SOURCE
    return ImportInput(**scope().model_dump(), message_id=source["_id"], fingerprint=fingerprint(source))


def parsed(raw):
    return ReportDraft.model_validate({"items": [{"task": "검색 화면 수정", "status": "IN_PROGRESS", "evidence": raw}]})


def fetch_one(endpoint, params):
    assert endpoint == "chat.getMessage" and params["msgId"] == SOURCE["_id"]
    return {"message": copy.deepcopy(SOURCE)}


def run_import(db, **changes):
    args = {"db": db, "user": USER, "payload": selection(), "fetch": fetch_one,
        "parse": parsed, "model": "gemma3:4b", "reauthorize": lambda: USER}
    args.update(changes)
    return import_message(**args)


def test_preview_reads_own_text_only_and_never_persists(db):
    messages = [SOURCE,
        {**SOURCE, "_id": "other-person", "u": {"_id": "other", "username": "other"}},
        {**SOURCE, "_id": "other-room", "rid": "other"},
        {**SOURCE, "_id": "system", "t": "removed-message"},
        {**SOURCE, "_id": "query", "msg": "오늘 보고"},
        {**SOURCE, "_id": "confirm", "msg": "확정 12345678"},
        {**SOURCE, "_id": "empty", "msg": "", "attachments": [{}]},
        {**SOURCE, "_id": "out-of-range", "ts": "2026-09-06T04:00:00Z"}]
    def fetch(endpoint, params):
        assert endpoint == "groups.history" and params["roomId"] == "room1"
        assert params["count"] == 50 and params["offset"] == 0
        return {"messages": messages}
    result = preview_messages(db, USER, scope(), fetch)
    assert [row["message_id"] for row in result["items"]] == [SOURCE["_id"]]
    assert not result["persisted"] and not result["llm_used"]
    assert result["items"][0]["submitted_at"] == "2026-09-07T13:00:00"
    assert SOURCE["_id"] in result["items"][0]["source_url"]
    assert count(db, ChatDraft) == count(db, Report) == count(db, ChatDraftRevision) == 0


def test_selected_import_is_draft_only_preserves_source_and_retries(db):
    result = run_import(db)
    assert result["created"] and result["draft"]["state"] == "DRAFT"
    assert result["draft"]["submitted_at"] == "2026-09-07T13:00:00"
    assert result["draft"]["raw_message"] == SOURCE["msg"]
    assert result["draft"]["report_ids"] == [] and count(db, Report) == 0
    audit = db.scalar(select(ChatDraftRevision))
    assert audit.action == "IMPORT" and audit.actor_id == USER["_id"]
    def no_ai(_):
        raise AssertionError("Repeated source must not call LLM")
    repeated = run_import(db, parse=no_ai)
    assert not repeated["created"] and count(db, ChatDraft) == count(db, ChatDraftRevision) == 1
    preview = preview_messages(db, USER, scope(), lambda *_: {"messages": [SOURCE]})
    assert preview["items"][0]["existing"] == "DRAFT"
    draft = db.get(ChatDraft, result["draft"]["id"])
    chat_request = {"_id": "confirm-old", "rid": "room1", "u": SOURCE["u"], "ts": datetime.now().astimezone().isoformat(), "msg": "확정"}
    assert "화면에서 확인" in confirm_from_chat(db, chat_request)
    assert count(db, Report) == 0
    save_review(db, draft, USER, edit(draft), True)
    assert count(db, Report) == 1
    assert db.scalar(select(Report)).created_at == datetime(2026,9,7,13)
    again = run_import(db, parse=no_ai)
    assert not again["created"] and again["draft"]["state"] == "CONFIRMED"


@pytest.mark.parametrize("changes", [{"rid": "other"}, {"u": {"_id": "other", "username": "other"}},
    {"ts": "2026-09-06T04:00:00Z"}, {"t": "system"}, {"msg": ""}])
def test_recheck_rejects_other_owner_room_period_and_nontext(db, changes):
    source = {**SOURCE, **changes}
    with pytest.raises(HTTPException) as exc:
        run_import(db, payload=selection(source), fetch=lambda *_: {"message": source})
    assert exc.value.status_code == 404 and count(db, ChatDraft) == 0


def test_forged_room_never_calls_rocket(db):
    def forbidden(*_):
        raise AssertionError("Out of scope Rocket request")
    payload = scope().model_copy(update={"room_id": "real-company-room"})
    with pytest.raises(HTTPException) as exc:
        preview_messages(db, USER, payload, forbidden)
    assert exc.value.status_code == 403


def test_changed_source_requires_new_preview(db):
    with pytest.raises(HTTPException) as exc:
        run_import(db, fetch=lambda *_: {"message": {**SOURCE, "msg": "원문이 바뀌었습니다"}})
    assert exc.value.status_code == 409 and count(db, ChatDraft) == 0


@pytest.mark.parametrize("failure", ["edit", "delete", "revoke", "model"])
def test_changes_during_ai_and_model_failure_never_save(db, failure):
    calls = []
    def fetch(*_):
        calls.append(1)
        if len(calls)>1:
            if failure == "delete":
                raise HTTPException(401, "source no longer available")
            if failure == "edit":
                return {"message": {**SOURCE, "editedAt": "2026-09-07T06:00:00Z"}}
        return {"message": copy.deepcopy(SOURCE)}
    def parser(raw):
        if failure == "model":
            raise LocalLLMError("synthetic failure")
        return parsed(raw)
    with pytest.raises((HTTPException, LocalLLMError)):
        run_import(db, fetch=fetch, parse=parser, reauthorize=lambda: {**USER, "room_id": "revoked"} if failure == "revoke" else USER)
    assert count(db, ChatDraft) == count(db, Report) == 0
    assert IMPORT_SLOT.acquire(blocking=False)
    IMPORT_SLOT.release()


@pytest.mark.parametrize("changes", [{"start": date(2026,7,1)}, {"start": date(2026,9,8)},
    {"end": date.today()+timedelta(days=2)}, {"offset": 1}, {"offset": 50},
    {"as_of": datetime(2026,9,7)}])
def test_range_and_pagination_validation(changes):
    with pytest.raises(ValidationError):
        PreviewInput.model_validate({**scope().model_dump(), **changes})


def test_snapshot_pagination_and_scan_cap(db):
    messages = [{**SOURCE, "_id": "page"+str(i)} for i in range(50)]
    first = preview_messages(db, USER, scope(), lambda *_: {"messages": messages})
    assert first["next_offset"] == 50
    last = scope(offset=1950, as_of=datetime.fromisoformat(first["as_of"]))
    result = preview_messages(db, USER, last, lambda *_: {"messages": messages})
    assert result["next_offset"] is None and result["scan_limit_reached"]
    assert boundaries(last)[0].isoformat().startswith("2026-09-07T00:00:00+09:00")


def test_import_slot_is_bounded(db):
    assert IMPORT_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as exc:
            run_import(db)
        assert exc.value.status_code == 429
    finally:
        IMPORT_SLOT.release()


def test_import_http_requires_auth_and_forwards_user_credentials(db, monkeypatch):
    with TestClient(app) as client:
        assert client.post("/api/review/imports/preview", json=scope().model_dump(mode="json")).status_code == 422
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: USER
    def request(method, endpoint, headers, params):
        assert method == "GET" and headers == {"X-User-Id": "employee1", "X-Auth-Token": "synthetic-token"}
        assert endpoint == "groups.history"
        return {"messages": [SOURCE]}
    monkeypatch.setattr("app.rocketchat.review_app.chat_request", request)
    try:
        with TestClient(app) as client:
            response = client.post("/api/review/imports/preview", json=scope().model_dump(mode="json"),
                headers={"X-Rocket-User": "employee1", "X-Rocket-Token": "synthetic-token"})
            assert response.status_code == 200 and len(response.json()["items"]) == 1
            assert count(db, ChatDraft) == 0
    finally:
        app.dependency_overrides.clear()
