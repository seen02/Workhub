import json
import asyncio
from datetime import date, datetime

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import ChatDraft
from app.rocketchat.commands import manager_command_for, team_query_command_for
from app.rocketchat.manager_query import ManagerQuery, ManagerQueryProvider, fallback_manager_query
from app.rocketchat.manager_service import (answer_manager_question, answer_structured_manager_query,
                                            format_structured_manager_answer, get_manager_dashboard)
from app.rocketchat.review_app import app, current_manager


def draft(identifier, author, hour, items, state="CONFIRMED"):
    return ChatDraft(
        id=identifier * 64, room_id=f"room-{author}", message_id=f"message-{identifier}",
        author_id=f"id-{author}", author_username=author, raw_message="synthetic",
        submitted_at=datetime(2026, 9, 9, hour, 0), model="gemma3:4b",
        ai_data=json.dumps(items, ensure_ascii=False), current_data=json.dumps(items, ensure_ascii=False),
        state=state, version=1,
    )


def test_manager_dashboard_uses_latest_confirmed_report_per_employee():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            draft("a", "employee-a", 9, [{"task": "오래된 업무", "project": "ai-assistant", "status": "IN_PROGRESS", "progress": 20, "issue": None}]),
            draft("b", "employee-a", 13, [
                {"task": "관리자 화면", "project": "ai-assistant", "status": "IN_PROGRESS", "progress": 70, "issue": None},
                {"task": "RAG 검색", "project": "ai-assistant", "status": "NOT_STARTED", "progress": None, "issue": None},
            ]),
            draft("c", "employee-b", 14, [{"task": "검색 품질", "project": "spatial-agent", "status": "DELAYED", "progress": 40, "issue": "정확도 확인 필요"}]),
            draft("d", "employee-c", 15, [{"task": "미확정", "project": "ai-assistant", "status": "DONE", "progress": None, "issue": None}], state="DRAFT"),
        ])
        db.commit()
        data = get_manager_dashboard(db, date(2026, 9, 9))
        assert data["kpis"] == {"reported_today": 2, "employee_count": 2, "task_count": 3, "average_progress": 55, "risk_count": 1}
        assert {row["name"] for row in data["projects"]} == {"AI업무비서 개발 프로젝트", "공간정보 Agent 프로젝트"}
        assert all(row["task"] != "오래된 업무" for row in data["risks"])
        answer, sources = answer_manager_question(data, "업무비서 프로젝트 어디까지 진행됐어?")
        assert "70%" in answer and "진행 중 1건" in answer and sources
    engine.dispose()


def test_team_dashboard_api_requires_session_and_serves_authorized_member():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(draft("e", "employee-a", 13, [{"task": "화면", "project": "ai-assistant", "status": "DONE", "progress": None, "issue": None}]))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            with TestClient(app) as client:
                assert client.get("/api/review/manager/dashboard").status_code == 422
                app.dependency_overrides[current_manager] = lambda: {"_id": "employee-a", "username": "employee-a"}
                response = client.get("/api/review/manager/dashboard")
                assert response.status_code == 200
                assert response.json()["kpis"]["employee_count"] == 1
                assert client.get("/api/review/manager/dashboard?date_from=2026-09-10&date_to=2026-09-09").status_code == 422
                assert client.get("/api/review/manager/dashboard?status=INVALID").status_code == 422
                page = client.get("/assets/manager.html")
                assert page.status_code == 200
                assert "전체 업무 현황" in page.text and "Rocket.Chat으로 돌아가기" in page.text
                assert 'id="filters"' in page.text and 'id="trends"' in page.text
        finally:
            app.dependency_overrides.clear()
    engine.dispose()


def test_manager_room_accepts_natural_questions_for_gemma_classification():
    message = {"_id": "q1", "rid": "manager-room", "msg": "오늘 employee-a 사원 보고 전부 보여줘",
               "u": {"_id": "admin", "username": "poc-admin"}}
    assert manager_command_for(message, "manager-room", "poc-admin", "bot") == (
        "manager", "오늘 employee-a 사원 보고 전부 보여줘")
    assert manager_command_for({**message, "u": {"_id": "other", "username": "other"}},
                               "manager-room", "poc-admin", "bot") is None


def test_shared_report_room_accepts_team_lookup_questions_only():
    message = {"_id": "q2", "rid": "reports-room",
               "msg": "오늘 AI업무비서 프로젝트 진행사항 알려줘",
               "u": {"_id": "employee-1", "username": "poc-employee"}}
    allowed = {"poc-employee", "poc-admin"}
    assert team_query_command_for(message, "reports-room", allowed, "bot") == (
        "team_query", "오늘 AI업무비서 프로젝트 진행사항 알려줘")
    assert team_query_command_for({**message, "msg": "안녕하세요"},
                                  "reports-room", allowed, "bot") is None
    assert team_query_command_for({**message, "u": {"_id": "stranger", "username": "stranger"}},
                                  "reports-room", allowed, "bot") is None
    assert team_query_command_for({**message, "u": {"_id": "bot", "username": "report-bot"}},
                                  "reports-room", allowed, "bot") is None


def test_fallback_manager_query_understands_common_free_form_questions():
    today = date(2026, 9, 10)
    employee = fallback_manager_query("오늘 김태인 사원 보고 다 보여줘", today)
    assert (employee.intent, employee.period, employee.target_date) == (
        "EMPLOYEE_REPORTS", "TODAY", today)
    assert "김태인" in employee.employee
    project = fallback_manager_query("오늘 업무비서 프로젝트 보고 전부 보여줘", today)
    assert (project.intent, project.project, project.target_date) == (
        "PROJECT_REPORTS", "ai-assistant", today)
    status = fallback_manager_query("공간정보 프로젝트 진행사항 알려줘", today)
    assert (status.intent, status.project, status.period) == (
        "PROJECT_STATUS", "spatial-agent", "LATEST")
    recent = fallback_manager_query("공간정보Agent 프로젝트 관련 보고된거 보여줘", today)
    assert (recent.intent, recent.project, recent.period, recent.target_date) == (
        "PROJECT_REPORTS", "spatial-agent", "RECENT", None)


def test_gemma_manager_query_uses_structured_output(monkeypatch):
    async def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gemma3:4b" and body["format"]["title"] == "ManagerQuery"
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "intent": "EMPLOYEE_REPORTS", "period": "TODAY", "target_date": None,
            "employee": "employee-a", "project": None,
        })}})

    monkeypatch.setenv("LOCAL_LLM_MODEL", "gemma3:4b")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    try:
        query = asyncio.run(ManagerQueryProvider(client).parse_question(
            "오늘 employee-a 사원 보고 보여줘", ["employee-a"], date(2026, 9, 10)))
    finally:
        asyncio.run(client.aclose())
    assert query.intent == "EMPLOYEE_REPORTS" and query.period == "TODAY"
    assert query.target_date == date(2026, 9, 10) and query.employee == "employee-a"


def test_structured_manager_queries_return_daily_employee_and_project_reports():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            draft("f", "employee-a", 9, [{"task": "보고 UI", "project": "ai-assistant", "status": "DONE", "progress": None, "issue": None}]),
            draft("g", "employee-a", 13, [{"task": "관리자 검색", "project": "ai-assistant", "status": "IN_PROGRESS", "progress": 60, "issue": None}]),
            draft("h", "employee-b", 14, [{"task": "공간 검색", "project": "spatial-agent", "status": "IN_PROGRESS", "progress": 40, "issue": None}]),
            draft("i", "employee-b", 10, [{"task": "공간 자료 정리", "project": "spatial-agent", "status": "DONE", "progress": None, "issue": None}]),
        ])
        db.commit()
        employee_query = ManagerQuery(intent="EMPLOYEE_REPORTS", period="TODAY",
                                      target_date=date(2026, 9, 9), employee="employee-a")
        answer, sources = answer_structured_manager_query(db, employee_query, date(2026, 9, 9))
        assert "확정 보고 2건" in answer and "보고 UI" in answer and "관리자 검색" in answer
        assert len(sources) == 2 and "공간 검색" not in answer

        project_query = ManagerQuery(intent="PROJECT_REPORTS", period="TODAY",
                                     target_date=date(2026, 9, 9), project="업무비서 프로젝트")
        answer, sources = answer_structured_manager_query(db, project_query, date(2026, 9, 9))
        assert "AI업무비서 개발 프로젝트" in answer and "확정 보고 2건" in answer
        assert "employee-a" in answer and "공간 검색" not in answer and len(sources) == 2

        status_query = ManagerQuery(intent="PROJECT_STATUS", project="공간정보 프로젝트")
        answer, sources = answer_structured_manager_query(db, status_query, date(2026, 9, 9))
        assert "진행률 40%" in answer and "공간 검색" in answer and len(sources) == 1

        recent_query = ManagerQuery(intent="PROJECT_REPORTS", period="RECENT", project="공간정보Agent")
        answer, sources = answer_structured_manager_query(db, recent_query, date(2026, 9, 9))
        assert "최근 기준" in answer and "확정 보고 2건" in answer
        assert "공간 검색" in answer and "공간 자료 정리" in answer and len(sources) == 2
        assert "1. 2026-09-09 14:00 · employee-b · 공간정보 Agent 프로젝트 · 공간 검색 — 진행 중 40%" in answer
        assert "\n2. 2026-09-09 10:00 · employee-b · 공간정보 Agent 프로젝트 · 공간 자료 정리 — 완료" in answer
    engine.dispose()


def test_manager_report_lines_do_not_break_dashboard_markdown_link():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(draft("j", "employee-a", 12, [{
            "task": "[UI 저장 테스트] 변경된 업무 내용", "project": "spatial-agent",
            "status": "IN_PROGRESS", "progress": 37,
            "next_action": "저장 후 값 다시 확인", "issue": "기능검증용 입력",
        }]))
        db.commit()
        query = ManagerQuery(intent="PROJECT_REPORTS", period="RECENT", project="공간정보Agent")
        answer, _ = answer_structured_manager_query(db, query, date(2026, 9, 9))
        assert "1. 2026-09-09 12:00 · employee-a · 공간정보 Agent 프로젝트" in answer
        assert "［UI 저장 테스트］" in answer and "\\[" not in answer and "\\]" not in answer
        assert " · 다음 작업: 저장 후 값 다시 확인 · 이슈: 기능검증용 입력" in answer
    engine.dispose()


def test_manager_chat_hides_individual_source_links():
    rendered = format_structured_manager_answer(
        "업무비서 프로젝트 진행률은 60%입니다.",
        ["http://127.0.0.1:3000/group/private?msg=secret"],
        "http://127.0.0.1:8003/assets/manager.html?access=test",
        "gemma3:4b",
        True,
    )
    assert "근거:" not in rendered and "원문" not in rendered and "private?msg=" not in rendered
    assert "확정 보고 DB" in rendered and "전체 프로젝트·직원·리스크 보기" in rendered


def test_dashboard_filters_expanded_risks_and_progress_trends():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        older = draft("k", "employee-a", 10, [{
            "task": "관리자 화면", "project": "ai-assistant",
            "status": "IN_PROGRESS", "progress": 40, "issue": None,
        }])
        older.submitted_at = datetime(2026, 9, 8, 10, 0)
        latest = draft("l", "employee-a", 11, [{
            "task": "관리자 화면", "project": "ai-assistant",
            "status": "IN_PROGRESS", "progress": 40, "issue": None,
        }])
        missing = draft("m", "employee-b", 12, [{
            "task": "검색 연결", "project": "spatial-agent",
            "status": "IN_PROGRESS", "progress": None, "issue": None,
        }])
        db.add_all([older, latest, missing])
        db.commit()

        filtered = get_manager_dashboard(
            db, date(2026, 9, 9), date_from=date(2026, 9, 8), date_to=date(2026, 9, 9),
            project="ai-assistant", employee="employee-a", status="IN_PROGRESS",
        )
        assert filtered["kpis"]["task_count"] == 1
        assert filtered["filters"] == {
            "date_from": "2026-09-08", "date_to": "2026-09-09",
            "project": "ai-assistant", "employee": "employee-a", "status": "IN_PROGRESS",
        }
        assert filtered["risks"][0]["risk_type"] == "STALLED"
        assert [point["average_progress"] for point in filtered["trends"]] == [40, 40]

        missing_progress = get_manager_dashboard(db, date(2026, 9, 9), employee="employee-b")
        assert missing_progress["risks"][0]["risk_type"] == "MISSING_PROGRESS"
        assert "진행률" in missing_progress["risks"][0]["reason"]
    engine.dispose()
