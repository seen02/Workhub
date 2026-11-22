from app.database import SessionLocal
from app.models import Report
from sqlalchemy import func, select


def test_seed_and_dashboard_project_aggregation(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["total_employees"] == 5
    assert len(payload["projects"]) == 4
    road = next(project for project in payload["projects"] if project["name"] == "도로명 컨설팅")
    assert road["progress"] == 77
    assert payload["kpis"]["delayed_count"] >= 1
    assert len(payload["trend"]) >= 2
    assert payload["trend"][-1]["report_count"] == 10


def test_report_is_parsed_validated_and_saved(client):
    employees = client.get("/api/employees").json()
    projects = client.get("/api/projects").json()
    employee_id = next(item["id"] for item in employees if item["name"] == "김진성")
    project_id = next(item["id"] for item in projects if item["name"] == "도로명 컨설팅")

    before = client.get("/api/dashboard").json()
    payload = {
        "employee_id": employee_id,
        "project_id": project_id,
        "raw_message": (
            "09:00~13:00 PostGIS 자료조사를 진행했습니다. "
            "공간질의 3개 중 2개를 완료했고 오후에는 FastAPI 연동 예정입니다. "
            "이슈는 없습니다."
        ),
    }
    preview = client.post("/api/reports/parse", json=payload)
    assert preview.status_code == 200
    assert preview.json()["elapsed_ms"] >= 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Report.id))) == 17

    preview_data = preview.json()
    preview_data["parsed"]["task"] = "직원이 수정한 PostGIS 조사"
    preview_data["parsed"]["progress"] = 71
    response = client.post("/api/reports", json={**payload, "parsed": preview_data["parsed"]})
    assert response.status_code == 201
    result = response.json()
    assert result["parsed"]["progress"] == 71
    assert result["parsed"]["duration_hours"] == 4
    assert result["parsed"]["issue"] is None
    assert result["parsed"]["task"] == "직원이 수정한 PostGIS 조사"

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Report.id))) == 18

    after = client.get("/api/dashboard").json()
    kim = next(item for item in after["employees"] if item["name"] == "김진성")
    assert kim["progress"] == 71
    assert kim["duration_hours"] >= 4
    assert after["kpis"]["average_progress"] >= before["kpis"]["average_progress"]

    duplicate = client.post("/api/reports", json={**payload, "parsed": preview_data["parsed"]})
    assert duplicate.status_code == 409


def test_report_history_filter_detail_and_revision(client):
    history = client.get("/api/reports", params={"search": "직원이 수정한"})
    assert history.status_code == 200
    item = history.json()["items"][0]
    assert item["employee"] == "김진성"

    detail = client.get(f"/api/reports/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["revisions"] == []

    edited = client.put(
        f"/api/reports/{item['id']}",
        json={
            "task": "PostGIS 공간질의 검증",
            "status": "IN_PROGRESS",
            "progress": 75,
            "duration_hours": 4,
            "issue": None,
            "next_action": "성능 테스트",
            "edit_reason": "발표 전 수치 정정",
        },
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["progress"] == 75
    assert len(body["revisions"]) == 1
    assert body["revisions"][0]["reason"] == "발표 전 수치 정정"


def test_chat_uses_dashboard_data(client):
    response = client.post("/api/chat", json={"message": "오늘 지연된 업무 알려줘"})
    assert response.status_code == 200
    payload = response.json()
    assert "철도연 시연영상" in payload["answer"]
    assert "tasks" in payload["sources"]


def test_llm_status_exposes_keyless_mock_runtime(client):
    response = client.get("/api/system/llm")
    assert response.status_code == 200
    assert response.json() == {
        "provider": "mock",
        "model": "deterministic-parser",
        "ready": True,
        "detail": "API Key 없이 실행되는 데모 파서",
    }


def test_employee_role_can_only_access_own_reports(client):
    headers = {"X-Demo-Role": "employee", "X-Demo-Employee-Id": "1"}
    employees = client.get("/api/employees", headers=headers)
    assert employees.status_code == 200
    assert [item["id"] for item in employees.json()] == [1]

    history = client.get("/api/reports", headers=headers).json()["items"]
    assert history
    assert {item["employee_id"] for item in history} == {1}
    assert client.get("/api/dashboard", headers=headers).status_code == 403
    assert client.get("/api/reports/8", headers=headers).status_code == 403


def test_employee_role_cannot_submit_for_another_employee(client):
    headers = {"X-Demo-Role": "employee", "X-Demo-Employee-Id": "1"}
    response = client.post(
        "/api/reports/parse",
        headers=headers,
        json={"employee_id": 2, "project_id": 1, "raw_message": "진행률 50% 업무를 진행했습니다."},
    )
    assert response.status_code == 403
