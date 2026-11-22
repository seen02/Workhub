import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.models import ChatPublication, Report
from app.rocketchat.publication import PublishInput, preview, publish
from app.rocketchat.review_service import save_review, serialize
from app.rocketchat.query import search_reports, parse_query
from app.rocketchat.workspace import private_members_ok
from app.rocketchat.worker import Worker
from test_chat_review import db, USER, make_draft, edit, count

TARGET = {"room_id": "shared", "name": "업무보고"}


@pytest.fixture
def personal(monkeypatch):
    cfg = {"personal_rooms": {"poc-employee": {"room_id": "room1", "name": "개인보고"}},
           "channels": {"reports": TARGET}}
    monkeypatch.setattr("app.rocketchat.workspace.settings", lambda: cfg)
    return cfg


def saved(db):
    d = make_draft(db)
    payload = edit(d)
    for item in payload.items:
        item.project = "ai-assistant"
    save_review(db, d, USER, payload, True)
    return d


def request_for(db, d):
    view = preview(db, d, TARGET)
    return PublishInput(version=view["version"], preview_hash=view["preview_hash"])


def test_private_save_does_not_leak_into_legacy_dashboard(db, personal):
    d = saved(db)
    assert count(db, Report) == 0
    assert serialize(db, d)["private_mode"]
    result = search_reports(db, USER["_id"], USER["room_id"], parse_query("오늘 보고"))
    assert len(result["items"]) == 2
    assert not search_reports(db, "other", USER["room_id"], parse_query("오늘 보고"))["items"]
    assert count(db, ChatPublication) == 0


def test_preview_has_only_selected_final_content_and_no_writes(db, personal):
    d = saved(db)
    view = preview(db, d, TARGET)
    assert "로켓챗 기반 업무 비서 AI Agent 개발" in view["text"]
    assert d.raw_message not in view["text"]
    assert "8003" not in view["text"] and "개인보고" not in view["text"]
    assert count(db, ChatPublication) == 0


def test_unconfirmed_and_unassigned_rejected(db, personal):
    d = make_draft(db)
    with pytest.raises(HTTPException): preview(db, d, TARGET)
    save_review(db, d, USER, edit(d), True)
    with pytest.raises(HTTPException) as error: preview(db, d, TARGET)
    assert error.value.status_code == 422


def test_publish_is_explicit_and_duplicate_click_is_idempotent(db, personal):
    d = saved(db)
    sent = []
    payload = request_for(db, d)
    first = publish(db, d.id, USER, payload, TARGET, lambda: None, lambda row: sent.append(row.text))
    second = publish(db, d.id, USER, payload, TARGET, lambda: None, lambda row: sent.append(row.text))
    assert first["state"] == "SENT" and second["already_sent"]
    assert len(sent) == 1 and count(db, ChatPublication) == 1 and count(db, Report) == 0


def test_stale_preview_and_wrong_target_rejected(db, personal):
    d = saved(db)
    payload = request_for(db, d)
    def never(*a): pytest.fail("Unexpected delivery")
    with pytest.raises(HTTPException):
        publish(db, d.id, USER, payload, {"room_id": "other", "name": "other"}, lambda: None, never)
    save_review(db, d, USER, edit(d, reason="다음 작업 추가", items=[{**i, "next_action": "검토"} for i in json.loads(d.current_data)]), True)
    with pytest.raises(HTTPException): publish(db, d.id, USER, payload, TARGET, lambda: None, never)
    assert count(db, ChatPublication) == 0


def test_uncertain_delivery_retries_same_id_and_locks_edit(db, personal):
    d = saved(db)
    payload = request_for(db, d)
    deliveries = {}
    def interrupted(row):
        deliveries[row.message_id] = row.text
        raise TimeoutError()
    with pytest.raises(HTTPException): publish(db, d.id, USER, payload, TARGET, lambda: None, interrupted)
    assert db.scalar(select(ChatPublication)).state == "PENDING"
    changed = edit(d)
    changed.items[0].task = "다른 내용"
    with pytest.raises(HTTPException): save_review(db, d, USER, changed, True)
    def resumed(row):
        assert deliveries[row.message_id] == row.text
    assert publish(db, d.id, USER, payload, TARGET, lambda: None, resumed)["state"] == "SENT"
    assert len(deliveries) == 1


def test_correction_preserves_original_and_requires_new_preview(db, personal):
    d = saved(db)
    publish(db, d.id, USER, request_for(db, d), TARGET, lambda: None, lambda row: None)
    original = db.scalar(select(ChatPublication)).text
    changed = edit(d)
    changed.items[0].task = "자료 조사 보완"
    save_review(db, d, USER, changed, True)
    assert count(db, ChatPublication) == 1
    assert "수정본" in preview(db, d, TARGET)["text"]
    publish(db, d.id, USER, request_for(db, d), TARGET, lambda: None, lambda row: None)
    assert count(db, ChatPublication) == 2
    assert db.scalars(select(ChatPublication).order_by(ChatPublication.version)).first().text == original


def test_unauthorized_or_wrong_author_never_publishes(db, personal):
    d = saved(db)
    payload = request_for(db, d)
    def denied(): raise HTTPException(403, "revoked")
    for user, auth in [({**USER, "_id": "other"}, lambda: None), (USER, denied)]:
        with pytest.raises(HTTPException):
            publish(db, d.id, user, payload, TARGET, auth, lambda row: pytest.fail("unexpected send"))
    assert count(db, ChatPublication) == 0


@pytest.mark.parametrize("members,total,expected", [(["alice","bot"],2,True),(["alice","bot","bob"],3,False),
    (["alice"],1,False),(["alice","bot"],3,False)])
def test_personal_room_requires_exact_members(members,total,expected):
    assert private_members_ok({"members":[{"username": n} for n in members],"total":total},"alice","bot") is expected


def test_worker_pauses_if_personal_room_gains_a_member():
    worker=Worker.__new__(Worker)
    worker.config={"personal_owner":"alice","username":"bot"}
    worker.room="private"
    worker.api=SimpleNamespace(call=lambda method,endpoint,**kw: {"group":{"t":"p"}} if endpoint=="groups.info" else
                              {"members":[{"username":n} for n in ["alice","bot","bob"]],"total":3})
    with pytest.raises(RuntimeError): worker.check_private_room()


def test_existing_publication_keeps_snapshot_after_template_change(db, personal, monkeypatch):
    d = saved(db)
    before = preview(db, d, TARGET)
    publish(db, d.id, USER, request_for(db, d), TARGET, lambda: None, lambda row: None)
    monkeypatch.setattr("app.rocketchat.publication.format_report", lambda *args: "새 양식")
    after = preview(db, d, TARGET)
    assert after["text"] == before["text"] and after["preview_hash"] == before["preview_hash"]
