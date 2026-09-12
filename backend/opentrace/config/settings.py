"""Environment-backed application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class Settings(BaseSettings):
    """Settings for the application."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    service_name: Literal["opentrace"] = "opentrace"
    debug: bool = False
    ai_enabled: bool = False
    ai_provider_id: str = "disabled"
    ai_provider_endpoint: str | None = None
    ai_model_small: str | None = None
    ai_model_medium: str | None = None
    ai_model_strong: str | None = None
    generation_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in _VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ValueError(f"LOG_LEVEL must be one of: {allowed}")
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Load and cache validated settings for the current process."""
    return Settings()
