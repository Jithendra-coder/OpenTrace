import pytest
from pydantic import ValidationError
from opentrace.config.settings import Settings, get_settings


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.service_name == "opentrace"
    assert settings.debug is False
    assert settings.ai_enabled is False


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.debug is True
    get_settings.cache_clear()


def test_ai_settings_are_optional_runtime_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("AI_PROVIDER_ID", "test-provider")
    monkeypatch.setenv("AI_MODEL_SMALL", "test-small")

    settings = Settings()

    assert settings.ai_enabled is True
    assert settings.ai_provider_id == "test-provider"
    assert settings.ai_model_small == "test-small"


def test_invalid_log_level_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ValidationError, match="LOG_LEVEL must be one of"):
        Settings()
