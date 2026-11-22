import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient

from workhub_demo.api import create_app
from workhub_demo.interpreters import OllamaInterpreter


EDITOR = {"X-Demo-User": "demo-editor"}
OBSERVER = {"X-Demo-User": "demo-observer"}
EXPLICIT = "DEMO-101 완료 | 목록 화면 검토를 마쳤습니다."
NATURAL = "목록 화면 검토를 마쳤습니다."


@pytest.fixture
def workspace(tmp_path):
    db_path = tmp_path / "demo.sqlite3"
    with TestClient(create_app(db_path), headers=EDITOR) as client:
        yield client, db_path


def draft_report(client, text=EXPLICIT):
    response = client.post("/reports", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()


def confirm_url(draft):
    return f"/reports/{draft['id']}/confirm"


def assert_unpublished(client):
    assert client.get("/channel").json() == []
    task = client.get("/tasks").json()[0]
    assert (task["status"], task["version"]) == ("in_progress", 1)


def test_model_stub_produces_draft_and_only_confirmation_changes_state(workspace):
    client, _ = workspace
    draft = draft_report(client, NATURAL)
    assert (draft["source"], draft["task_id"], draft["status"]) == ("fixture", "DEMO-101", "done")
    assert_unpublished(client)

    response = client.post(confirm_url(draft))
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["message"] == "[DEMO-101] 완료 · " + NATURAL
    assert client.get("/tasks").json()[0]["version"] == receipt["document_version"] == 2
    assert client.get("/tasks").json()[0]["status"] == "done"
    assert client.get("/channel").json() == [receipt]


def test_explicit_task_and_status_skip_model(tmp_path):
    def fail_if_called(request):
        pytest.fail("The model must be skipped for an explicit report")

    interpreter = OllamaInterpreter("test-model", httpx.MockTransport(fail_if_called))
    with TestClient(create_app(tmp_path / "demo.sqlite3", interpreter), headers=EDITOR) as client:
        assert draft_report(client)["source"] == "explicit"


def test_permission_revoked_after_draft_blocks_confirmation(workspace):
    client, db_path = workspace
    draft = draft_report(client)
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("UPDATE access SET can_update = 0 WHERE actor = ?", ("demo-editor",))
    assert client.post(confirm_url(draft)).status_code == 403
    assert_unpublished(client)


def test_read_permission_does_not_allow_writing_or_confirming_another_draft(workspace):
    client, _ = workspace
    draft = draft_report(client)
    visible = client.get("/tasks", headers=OBSERVER).json()
    assert any(task["id"] == "DEMO-101" for task in visible)
    assert client.post("/reports", headers=OBSERVER, json={"text": EXPLICIT}).status_code == 422
    assert client.post(confirm_url(draft), headers=OBSERVER).status_code == 404
    assert_unpublished(client)


def test_stale_draft_cannot_overwrite_newer_document(workspace):
    client, _ = workspace
    older = draft_report(client, "DEMO-101 진행 | 검토 진행 중")
    newer = draft_report(client)
    assert client.post(confirm_url(newer)).status_code == 200
    assert client.post(confirm_url(older)).status_code == 409
    assert client.get("/channel").json()[0]["draft_id"] == newer["id"]
    assert len(client.get("/channel").json()) == 1
    assert client.get("/tasks").json()[0]["status"] == "done"


def test_concurrent_confirmations_publish_once_and_retry_survives_restart(workspace):
    client, db_path = workspace
    draft = draft_report(client)
    gate = Barrier(2, timeout=5)

    def send_confirmation():
        gate.wait()
        return client.post(confirm_url(draft))

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [executor.submit(send_confirmation) for _ in range(2)]
        first, second = [item.result(timeout=10) for item in pending]

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    with TestClient(create_app(db_path), headers=EDITOR) as restarted:
        assert restarted.post(confirm_url(draft)).json() == first.json()
        assert restarted.get("/channel").json() == [first.json()]
        assert restarted.get("/tasks").json()[0]["version"] == 2


def test_failed_channel_write_rolls_back_document_and_allows_retry(workspace):
    client, db_path = workspace
    draft = draft_report(client)
    with closing(sqlite3.connect(db_path)) as db, db:
        db.executescript("""
            CREATE TRIGGER fail_publication BEFORE INSERT ON publications
            BEGIN SELECT RAISE(ABORT, 'simulated channel write failure'); END;
        """)

    with pytest.raises(sqlite3.IntegrityError, match="simulated channel write failure"):
        client.post(confirm_url(draft))
    assert_unpublished(client)

    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("DROP TRIGGER fail_publication")
    receipt = client.post(confirm_url(draft))
    assert receipt.status_code == 200
    assert client.get("/channel").json() == [receipt.json()]
    assert client.get("/tasks").json()[0]["version"] == 2


def test_unclear_report_does_not_create_draft(workspace):
    client, db_path = workspace
    response = client.post("/reports", json={"text": "검토는 했지만 어느 업무인지 모르겠습니다."})
    assert response.status_code == 422
    assert_unpublished(client)
    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_ollama_returns_structured_proposal_from_editable_candidates(tmp_path):
    def local_model(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model" and payload["stream"] is False
        assert payload["format"]["required"] == ["proposal"]
        assert json.loads(payload["messages"][1]["content"]) == {
            "report": NATURAL,
            "task_candidates": [{"task_id": "DEMO-101", "title": "목록 화면 검토"}],
        }
        proposal = {"task_id": "DEMO-101", "status": "done", "summary": NATURAL}
        return httpx.Response(200, json={"message": {"content": json.dumps({"proposal": proposal})}})

    interpreter = OllamaInterpreter("test-model", httpx.MockTransport(local_model))
    with TestClient(create_app(tmp_path / "demo.sqlite3", interpreter), headers=EDITOR) as client:
        assert draft_report(client, NATURAL)["source"] == "ollama"
        assert_unpublished(client)


@pytest.mark.parametrize(
    ("model_content", "expected_status"),
    [
        ('{"proposal":{"task_id":"DEMO-202","status":"done","summary":"검토 완료"}}', 422),
        ('{"proposal":null}', 422),
        ("invalid model output", 502),
    ],
)
def test_generated_output_cannot_write_or_select_an_inaccessible_task(tmp_path, model_content, expected_status):
    def local_model(request):
        return httpx.Response(200, json={"message": {"content": model_content}})

    interpreter = OllamaInterpreter("test-model", httpx.MockTransport(local_model))
    with TestClient(create_app(tmp_path / "demo.sqlite3", interpreter), headers=EDITOR) as client:
        response = client.post("/reports", json={"text": NATURAL})
        assert response.status_code == expected_status
        assert_unpublished(client)
