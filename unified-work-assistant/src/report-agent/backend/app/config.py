from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "업무 비서 AI Agent"
    database_url: str = "sqlite:///./work_assistant.db"
    llm_provider: str = "local"
    local_llm_model: str = "gemma3:4b"
    ollama_base_url: str = "http://localhost:11434"
    local_llm_timeout_seconds: float = 120
    local_llm_retries: int = 2
    local_llm_fallback_to_mock: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auth_mode: str = "demo"
    jwt_jwks_url: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = ""
    jwt_role_claim: str = "role"
    jwt_employee_id_claim: str = "employee_id"
    jwt_manager_role: str = "manager"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
