from .base import LLMProvider
from .local import LocalProvider
from .mock import MockProvider
from ..config import get_settings


def get_provider() -> LLMProvider:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider in {"local", "ollama"}:
        return LocalProvider()
    if provider == "mock":
        return MockProvider()
    raise ValueError(f"지원하지 않는 LLM_PROVIDER입니다: {settings.llm_provider}")


async def get_provider_status() -> dict[str, str | bool]:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return {
            "provider": "mock",
            "model": "deterministic-parser",
            "ready": True,
            "detail": "API Key 없이 실행되는 데모 파서",
        }
    if provider in {"local", "ollama"}:
        return await LocalProvider.status()
    return {
        "provider": provider,
        "model": "unknown",
        "ready": False,
        "detail": "지원하지 않는 Provider",
    }
