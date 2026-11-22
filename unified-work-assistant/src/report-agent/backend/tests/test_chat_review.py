import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import ChatDraft, ChatDraftRevision, Employee, Report, ReportRevision, Task
from app.rocketchat.draft import ReportDraft
from app.rocketchat.review_app import app, current_user
from app.rocketchat.review_service import ReviewEdit, owned_draft, register_draft, save_review, serialize
from app.schemas import ReportUpdate
from app.services import get_dashboard, get_report_detail, update_report

USER = {"_id": "employee1", "username": "poc-employee", "room_id": "room1"}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def make_draft(db, message_id="source1", raw="자료 조사 완료. 화면 수정 중."):
    parsed = ReportDraft.model_validate({"items": [
        {"task": "자료 조사", "status": "DONE", "evidence": "자료 조사 완료"},
        {"task": "화면 수정", "status": "IN_PROGRESS", "evidence": "화면 수정 중"},
    ]})
    return register_draft(db, {"_id": message_id, "rid": "room1", "u": {"_id": "employee1", "username": "poc-employee"},
                              "ts": datetime.now().astimezone().isoformat()}, raw, parsed, "gemma3:4b")


def edit(entity, **changes):
    result = {"version": entity.version, "items": json.loads(entity.current_data), "reason": "직원이 내용 확인"}
    result.update(changes)
    return ReviewEdit.model_validate(result)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_register_is_idempotent_and_draft_is_not_a_report(db):
    entity = make_draft(db)
    assert make_draft(db).id == entity.id
    assert count(db, ChatDraft) == 1
    assert count(db, Report) == 0
    assert count(db, Employee) == 0


@pytest.mark.parametrize("user", [{**USER, "_id": "attacker"}, {**USER, "room_id": "other"}])
def test_other_author_or_room_cannot_access(db, user):
    entity = make_draft(db)
    with pytest.raises(HTTPException) as exc:
        owned_draft(db, entity.id, user)
    assert exc.value.status_code == 404


def test_draft_edit_records_before_after_but_no_confirmed_report(db):
    entity = make_draft(db)
    payload = edit(entity)
    payload.items[0].task = "수정한 자료 조사"
    save_review(db, entity, USER, payload, False)
    assert entity.version == 2
    assert count(db, Report) == 0
    revision = db.scalar(select(ChatDraftRevision))
    assert "수정한 자료 조사" in revision.after_data
    assert "수정한 자료 조사" not in revision.before_data


def test_multi_task_confirm_atomic_and_unknown_progress_stays_null(db):
    entity = make_draft(db)
    save_review(db, entity, USER, edit(entity), True)
    assert entity.state == "CONFIRMED"
    assert count(db, Report) == 2 and count(db, Task) == 2
    assert all(report.progress is None for report in db.scalars(select(Report)))
    assert all(task.progress is None for task in db.scalars(select(Task)))
    dashboard = get_dashboard(db)
    assert dashboard["employees"][0]["progress"] is None
    assert dashboard["projects"][0]["progress"] is None
    assert dashboard["kpis"]["delayed_count"] == 0
    assert len(serialize(db, entity)["report_ids"]) == 2


def test_double_click_confirmation_is_idempotent(db):
    entity = make_draft(db)
    payload = edit(entity)
    save_review(db, entity, USER, payload, True)
    save_review(db, entity, USER, payload, True)
    assert count(db, Report) == 2
    assert count(db, ChatDraftRevision) == 1


def test_confirmed_edit_updates_same_reports_and_keeps_audit(db):
    entity = make_draft(db)
    save_review(db, entity, USER, edit(entity), True)
    ids = serialize(db, entity)["report_ids"]
    payload = edit(entity)
    payload.items[1].progress = 45
    payload.items[1].next_action = "내일 화면 테스트"
    save_review(db, entity, USER, payload, True)
    assert serialize(db, entity)["report_ids"] == ids
    assert db.get(Report, ids[1]).progress == 45
    assert db.get(Task, db.get(Report, ids[1]).task_id).progress == 45
    assert count(db, ChatDraftRevision) == 2
    assert count(db, ReportRevision) == 4


def test_clearing_progress_after_confirmation_keeps_null(db):
    entity = make_draft(db)
    payload = edit(entity)
    payload.items[1].progress = 40
    save_review(db, entity, USER, payload, True)
    payload = edit(entity)
    payload.items[1].progress = None
    save_review(db, entity, USER, payload, True)
    assert all(task.progress is None for task in db.scalars(select(Task)))


def test_unknown_status_blocks_entire_batch(db):
    entity = make_draft(db)
    payload = edit(entity)
    payload.items[1].status = "UNKNOWN"
    with pytest.raises(HTTPException) as exc:
        save_review(db, entity, USER, payload, True)
    assert exc.value.status_code == 422
    assert count(db, Report) == 0
    assert entity.version == 1


def test_stale_version_cannot_overwrite(db):
    entity = make_draft(db)
    stale = edit(entity)
    save_review(db, entity, USER, edit(entity), False)
    with pytest.raises(HTTPException) as exc:
        save_review(db, entity, USER, stale, False)
    assert exc.value.status_code == 409


def test_copied_message_cannot_duplicate_confirmed_report(db):
    first = make_draft(db)
    save_review(db, first, USER, edit(first), True)
    copied = make_draft(db, "another-source")
    with pytest.raises(HTTPException) as exc:
        save_review(db, copied, USER, edit(copied), True)
    assert exc.value.status_code == 409
    assert count(db, Report) == 2


def test_legacy_demo_edit_cannot_bypass_rocket_auth(db):
    entity = make_draft(db)
    save_review(db, entity, USER, edit(entity), True)
    report_id = serialize(db, entity)["report_ids"][0]
    with pytest.raises(HTTPException) as exc:
        update_report(db, report_id, ReportUpdate(task="우회 수정", status="DONE", progress=100))
    assert exc.value.status_code == 409
    detail = get_report_detail(db, report_id)
    assert entity.id in detail["review_url"]
    assert entity.message_id in detail["source_url"]


def test_review_api_requires_real_auth_headers():
    with TestClient(app) as client:
        assert client.get("/api/review/drafts").status_code == 422


@pytest.mark.parametrize("progress", [-1, 101, 1.5, "40"])
def test_review_api_rejects_invalid_progress(db, progress):
    entity = make_draft(db)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: USER
    try:
        with TestClient(app) as client:
            payload = edit(entity).model_dump()
            payload["items"][0]["progress"] = progress
            response = client.post(f"/api/review/drafts/{entity.id}/confirm", json=payload)
            assert response.status_code == 422
            assert count(db, Report) == 0
    finally:
        app.dependency_overrides.clear()


def test_static_review_page_has_security_headers():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "수정할 보고 선택" in response.text
        assert "내용 저장" in response.text
        assert "업무보고방에 보내기" in response.text
        assert "이전 보고 가져오기" not in response.text


def test_manual_is_public_read_only_and_linked_from_review():
    with TestClient(app) as client:
        response = client.get("/assets/guide.html")
        assert response.status_code == 200
        assert "보고 쓰기 → 확인하기 → 다시 찾기" in response.text
        assert "다른 구성원도 볼 수 있습니다" in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert '/assets/team-guide.html' in client.get('/').text
        assert '/assets/guide.html' in client.get('/assets/team-guide.html').text
        assert client.get('/assets/guide.css').status_code == 200
        assert client.get('/assets/guide.js').status_code == 200
        assert client.get('/assets/manual.css').status_code == 200
        assert 'id="mechanism-title"' in response.text
        assert response.text.count('class="manual-panel"') == 6
        assert '메뉴 미구현' in response.text
