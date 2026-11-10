import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Enterprise Career Agent V3"
    app_api_key: SecretStr = SecretStr("change-me")
    tenant_api_keys_json: SecretStr | None = None
    database_url: str = "sqlite:///./data/agent_v3.db"
    auto_create_schema: bool = True

    llm_provider: str = "mock"
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: int = Field(default=60, ge=5, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    dashscope_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None

    jooble_api_key: SecretStr | None = None
    jooble_api_host: str = ""

    knowledge_dir: Path = Path("knowledge")
    max_resume_chars: int = Field(default=30_000, ge=1_000, le=100_000)
    max_jd_chars: int = Field(default=20_000, ge=1_000, le=100_000)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        provider = self.llm_provider.lower()
        if provider not in {"mock", "dashscope", "openai"}:
            raise ValueError("LLM_PROVIDER must be mock, dashscope, or openai")
        if provider == "dashscope" and not self.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required for dashscope")
        if provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for openai")
        if self.app_env.lower() == "production":
            value = self.app_api_key.get_secret_value()
            if not self.tenant_api_keys_json:
                raise ValueError("TENANT_API_KEYS_JSON is required in production")
            if value in {"change-me", "replace-with-a-long-random-value"}:
                raise ValueError("Replace the development APP_API_KEY in production")
            try:
                tenant_keys = json.loads(self.tenant_api_keys_json.get_secret_value())
            except json.JSONDecodeError as exc:
                raise ValueError("TENANT_API_KEYS_JSON must be valid JSON") from exc
            if not isinstance(tenant_keys, dict) or not tenant_keys:
                raise ValueError("TENANT_API_KEYS_JSON must contain at least one tenant")
            if any(not isinstance(key, str) or len(key) < 24 for key in tenant_keys.values()):
                raise ValueError("Every production tenant API key must be at least 24 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
