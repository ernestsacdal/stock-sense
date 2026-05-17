from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(...)
    backend_cors_origins: str = Field(default="http://localhost:3000")
    # OpenRouter is OpenAI-compatible — we use the openai SDK against
    # https://openrouter.ai/api/v1. Empty key = stub mode.
    openrouter_api_key: str = Field(default="")
    # Default to DeepSeek V3 (cheap + strong at SQL/reasoning). Swap to
    # qwen/qwen-2.5-72b-instruct, deepseek/deepseek-r1, or any other
    # OpenRouter-hosted model via env without code changes.
    openrouter_model: str = Field(default="deepseek/deepseek-chat")

    jwt_secret: str = Field(...)
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_ttl_min: int = Field(default=15)
    jwt_refresh_ttl_days: int = Field(default=7)

    refresh_cookie_name: str = Field(default="stocksense_refresh")
    refresh_cookie_secure: bool = Field(default=False)
    refresh_cookie_domain: str = Field(default="")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
