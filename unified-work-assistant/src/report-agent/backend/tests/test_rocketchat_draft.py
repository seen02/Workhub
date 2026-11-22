import json
from datetime import datetime, timezone

import httpx
import pytest

from app.llm.local import LocalLLMError
from app.rocketchat.draft import DraftProvider, DraftTask, ReportDraft, render_draft, render_chat_draft
from app.rocketchat.worker import report_body, Worker


def message(text="!보고 자료조사를 완료했습니다.", **overrides):
    return {"_id": "m1", "rid": "test-room", "msg": text,
            "u": {"_id": "employee", "username": "poc-employee"}, **overrides}


@pytest.mark.parametrize("text,expected", [
    ("!보고 자료조사를 완료했습니다.", "자료조사를 완료했습니다."),
    ("!보고\n자료조사를 완료했습니다.", "자료조사를 완료했습니다."),
    ("!보고서 내용입니다.", None), ("그냥 잡담입니다.", None), ("!보고", ""),
])
def test_explicit_trigger(text, expected):
    assert report_body(message(text), "test-room", {"poc-employee"}, "bot") == expected


@pytest.mark.parametrize("overrides", [
    {"rid": "real-work-room"}, {"tmid": "thread"}, {"t": "r"},
    {"u": {"_id": "bot", "username": "poc-employee"}},
    {"u": {"_id": "unknown", "username": "other-employee"}},
])
def test_ignore_out_of_scope_messages(overrides):
    assert report_body(message(**overrides), "test-room", {"poc-employee"}, "bot") is None


@pytest.mark.anyio
async def test_draft_uses_real_schema_and_separates_tasks():
    raw = "자료조사는 완료. 화면 수정은 진행 중."
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gemma3:4b"
        assert "think" not in body
        assert body["format"]["additionalProperties"] is False
        assert body["options"]["temperature"] == 0
        assert "구체적인 대상과 작업 행위를 유지" in body["messages"][0]["content"]
        assert "관리자 보고 검색 형식 검증" in body["messages"][0]["content"]
        result = {"items": [
            {"task": "자료조사", "status": "DONE", "evidence": "자료조사는 완료"},
            {"task": "화면 수정", "status": "IN_PROGRESS", "evidence": "화면 수정은 진행 중"},
        ]}
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama") as client:
        result = await DraftProvider(client).parse_draft(raw)
    assert len(result.items) == 2
    assert result.items[1].status == "IN_PROGRESS"


@pytest.mark.anyio
@pytest.mark.parametrize("reply", [
    {"items": []},
    {"items": [{"task": "없는 업무", "status": "DONE", "evidence": "지어낸 근거"}]},
    {"items": [{"task": "자료조사", "status": "INVALID", "evidence": "자료조사"}]},
])
async def test_no_mock_on_invalid_output(reply):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"message": {"content": json.dumps(reply)}})
    ), base_url="http://ollama") as client:
        provider = DraftProvider(client)
        provider.retries = 1
        with pytest.raises(LocalLLMError):
            await provider.parse_draft("자료조사를 완료했습니다.")


def test_company_format_kst_and_no_cross_task_percentage():
    draft = ReportDraft(items=[
        DraftTask(task="자료 조사", status="IN_PROGRESS", evidence="자료 조사 진행률 40%"),
        DraftTask(task="발표 준비", status="UNKNOWN", evidence="발표 준비를 보고합니다"),
    ])
    result = render_draft(draft, "@all", datetime(2026, 9, 8, 4, tzinfo=timezone.utc))
    assert "9/8(화) 13시 KST" in result
    assert "**1. 자료 조사**\n🔄 진행 중 · 진행률 **40%**" in result
    assert "**2. 발표 준비**\n❔ 상태 확인 필요\n" in result
    assert "100%" not in result
    assert "@all" not in result
    assert "확정 보고 DB에는 저장하지 않았습니다" in result


def test_done_status_does_not_invent_numeric_progress():
    draft = ReportDraft(items=[DraftTask(task="자료조사", status="DONE", evidence="자료조사 완료했습니다")])
    result = render_draft(draft, "테스트", datetime.now(timezone.utc))
    assert "✅ 완료" in result
    assert "100%" not in result


def test_chat_draft_has_one_task_list_and_separate_confirmation():
    draft = ReportDraft(items=[
        DraftTask(task="발표자료 수정", status="DONE", evidence="발표자료 수정 완료"),
        DraftTask(task="검색 화면", status="IN_PROGRESS", evidence="검색 화면 40% 진행"),
    ])
    result = render_chat_draft(draft, "@all", datetime(2026, 9, 8, 4, tzinfo=timezone.utc),
                               "abcdef123456", "gemma3:4b", 12.5)
    assert result.count("발표자료 수정") == 1
    assert "완료 1건 · 진행 중 1건" in result
    assert "\n\n**2. 검색 화면**\n" in result
    assert result.count("40%") == 1
    assert "100%" not in result
    assert "@all" not in result
    assert "`확정 abcdef12`" in result
    assert "http://127.0.0.1:8003/#abcdef123456" in result
    assert "확정 보고 DB에 저장되지 않았어요" in result
    assert "처리 12.5초" in result


@pytest.mark.parametrize("status", ["DONE", "IN_PROGRESS", "NOT_STARTED", "DELAYED", "UNKNOWN"])
@pytest.mark.parametrize("evidence", ["검색 화면 수정", "검색 화면 수정 40%"])
def test_only_in_progress_displays_progress(status, evidence):
    draft = ReportDraft(items=[DraftTask(task="검색 화면", status=status, evidence=evidence)])
    result = render_draft(draft, "테스트", datetime.now(timezone.utc), include_evidence=False)
    assert ("진행률" in result) == (status == "IN_PROGRESS")
    assert ("40%" in result) == (status == "IN_PROGRESS" and "40%" in evidence)


def test_cursor_initialization_does_not_import_old_history(tmp_path, monkeypatch):
    class FakeAPI:
        user_id = "bot"
        def __init__(self, config): pass
        def call(self, method, endpoint, body=None, params=None):
            assert params["oldest"] > "2026-01-01"
            return {"messages": [message(ts="2026-09-08T04:00:00.000Z")]}
    monkeypatch.setattr("app.rocketchat.worker.ChatAPI", FakeAPI)
    worker = Worker({"room_id": "test-room", "allowed_usernames": ["poc-employee"]}, tmp_path / "state.db")
    worker.poll()
    worker.poll()
    assert worker.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    worker.db.close()


def test_workers_can_share_one_authenticated_bot_client(tmp_path, monkeypatch):
    class SharedAPI:
        user_id = "bot"

    shared = SharedAPI()
    monkeypatch.setattr("app.rocketchat.worker.ChatAPI", lambda config: (_ for _ in ()).throw(
        AssertionError("Worker must not log in again when a shared client is supplied")))
    first = Worker({"room_id": "room-1", "allowed_usernames": ["employee-1"]},
                   tmp_path / "one.db", shared)
    second = Worker({"room_id": "room-2", "allowed_usernames": ["employee-2"]},
                    tmp_path / "two.db", shared)
    assert first.api is shared and second.api is shared
    first.db.close()
    second.db.close()


def test_reply_id_is_stable_and_room_scoped():
    worker = object.__new__(Worker)
    worker.room = "test-room"
    first = worker.reply_id("source")
    assert worker.reply_id("source") == first
    worker.room = "different-room"
    assert worker.reply_id("source") != first
