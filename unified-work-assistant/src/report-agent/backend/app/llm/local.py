from __future__ import annotations

import httpx
import asyncio

from .base import LLMProvider
from ..config import get_settings
from ..schemas import ParsedWorkReport


class LocalLLMError(RuntimeError):
    """Actionable error raised when the local Ollama runtime is unavailable."""


class LocalProvider(LLMProvider):
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.local_llm_model
        self.timeout = settings.local_llm_timeout_seconds
        self.retries = max(1, settings.local_llm_retries)
        self._client = client

    async def parse_report(
        self, raw_message: str, employee_name: str, project_name: str
    ) -> ParsedWorkReport:
        schema = ParsedWorkReport.model_json_schema()
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "한국어 업무보고에서 명시된 사실만 추출하세요. 직원명은 주어진 값을 사용하세요. "
                        "진행률이 명확하지 않으면 null, 이슈 없음은 null로 반환하세요. "
                        "시간은 HH:MM, 상태는 NOT_STARTED/IN_PROGRESS/DONE/DELAYED 중 하나입니다. "
                        "confidence는 추출 확신도를 0~1로 반환하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"직원: {employee_name}\n프로젝트: {project_name}\n"
                        f"업무보고:\n{raw_message}\n\nJSON Schema:\n{schema}"
                    ),
                },
            ],
        }
        if not self.model.startswith("gemma"):
            body["think"] = False
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = await self._post("/api/chat", body)
                content = response.json()["message"]["content"]
                return ParsedWorkReport.model_validate_json(content)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
        exc = last_error
        if isinstance(exc, httpx.ConnectError):
            raise LocalLLMError(
                "Ollama에 연결할 수 없습니다. Ollama를 실행하거나 docker compose up을 사용하세요."
            ) from exc
        if isinstance(exc, httpx.TimeoutException):
            raise LocalLLMError(
                f"로컬 모델 {self.model} 응답 시간이 초과되었습니다. 모델 로딩 상태를 확인하세요."
            ) from exc
        if isinstance(exc, httpx.HTTPStatusError):
            detail = exc.response.text[:300]
            raise LocalLLMError(
                f"Ollama 요청이 실패했습니다({exc.response.status_code}): {detail}"
            ) from exc
        raise LocalLLMError("로컬 LLM 응답이 업무보고 Schema를 통과하지 못했습니다.") from exc

    async def _post(self, path: str, body: dict) -> httpx.Response:
        if self._client:
            response = await self._client.post(path, json=body)
        else:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                response = await client.post(path, json=body)
        response.raise_for_status()
        return response

    @classmethod
    async def status(cls) -> dict[str, str | bool]:
        settings = get_settings()
        base_url = settings.ollama_base_url.rstrip("/")
        model = settings.local_llm_model
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=2) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
            names = {item.get("name", "") for item in response.json().get("models", [])}
            installed = model in names or any(name.startswith(f"{model}:") for name in names)
            return {
                "provider": "local",
                "model": model,
                "ready": installed,
                "detail": "로컬 모델 준비됨" if installed else f"ollama pull {model} 실행 필요",
            }
        except (httpx.HTTPError, ValueError):
            return {
                "provider": "local",
                "model": model,
                "ready": False,
                "detail": "Ollama 연결 대기 중",
            }
