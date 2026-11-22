import json

import httpx
import pytest

from app.llm.local import LocalLLMError, LocalProvider


@pytest.mark.anyio
async def test_local_provider_sends_schema_and_validates_response():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "gemma3:4b"
        assert "think" not in payload
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0
        assert "progress" in payload["format"]["properties"]
        parsed = {
            "employee": "김진성",
            "task": "PostGIS 공간질의 자료조사",
            "start_time": "09:00",
            "end_time": "13:00",
            "duration_hours": 4,
            "status": "IN_PROGRESS",
            "progress": 67,
            "issue": None,
            "next_action": "FastAPI 연동",
            "confidence": 0.94,
        }
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(parsed)}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama"
    ) as client:
        result = await LocalProvider(client=client).parse_report(
            "09:00~13:00 PostGIS 자료조사, 3개 중 2개 완료", "김진성", "도로명 컨설팅"
        )

    assert result.progress == 67
    assert result.next_action == "FastAPI 연동"


@pytest.mark.anyio
async def test_local_provider_rejects_invalid_schema_response():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"message": {"content": '{"progress": 999}'}})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as client:
        with pytest.raises(LocalLLMError, match="Schema"):
            await LocalProvider(client=client).parse_report("업무 진행", "김진성", "테스트")


@pytest.mark.anyio
async def test_local_provider_retries_after_invalid_response():
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"message": {"content": '{"progress": 999}'}})
        parsed = {
            "employee": "김진성", "task": "재시도 검증", "start_time": None, "end_time": None,
            "duration_hours": None, "status": "IN_PROGRESS", "progress": 50, "issue": None,
            "next_action": "확인", "confidence": 0.8,
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(parsed)}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama") as client:
        result = await LocalProvider(client=client).parse_report("진행률 50%", "김진성", "테스트")
    assert calls == 2
    assert result.progress == 50
