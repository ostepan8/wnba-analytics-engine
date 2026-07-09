"""Unit tests for env-backed settings."""

from __future__ import annotations

import pytest

from wnba_engine.config import (
    DEFAULT_BALLDONTLIE_BASE_URL,
    DEFAULT_ESPN_BASE_URL,
    DEFAULT_KALSHI_BASE_URL,
    DEFAULT_POLYMARKET_GAMMA_BASE_URL,
    DEFAULT_WAYBACK_BASE_URL,
    load_settings,
)


def test_defaults(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "WNBA_ENGINE_DATABASE_URL",
        "WNBA_ENGINE_ESPN_BASE_URL",
        "WNBA_ENGINE_KALSHI_BASE_URL",
        "WNBA_ENGINE_POLYMARKET_GAMMA_BASE_URL",
        "WNBA_ENGINE_WAYBACK_BASE_URL",
        "WNBA_ENGINE_BALLDONTLIE_BASE_URL",
        "WNBA_ENGINE_KALSHI_API_KEY",
        "WNBA_ENGINE_BALLDONTLIE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    assert settings.espn_base_url == DEFAULT_ESPN_BASE_URL
    assert settings.kalshi_base_url == DEFAULT_KALSHI_BASE_URL
    assert settings.polymarket_gamma_base_url == DEFAULT_POLYMARKET_GAMMA_BASE_URL
    assert settings.wayback_base_url == DEFAULT_WAYBACK_BASE_URL
    assert settings.balldontlie_base_url == DEFAULT_BALLDONTLIE_BASE_URL
    assert settings.kalshi_api_key is None
    assert settings.balldontlie_api_key is None
    assert settings.min_request_interval_seconds == 0.5
    assert settings.wayback_min_request_interval_seconds == 1.5
    assert settings.balldontlie_min_request_interval_seconds == 0.15


def test_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WNBA_ENGINE_KALSHI_BASE_URL", "https://example.test/v2")
    monkeypatch.setenv("WNBA_ENGINE_KALSHI_API_KEY", "secret")
    monkeypatch.setenv("WNBA_ENGINE_MIN_REQUEST_INTERVAL_SECONDS", "1.25")
    settings = load_settings()
    assert settings.kalshi_base_url == "https://example.test/v2"
    assert settings.kalshi_api_key == "secret"
    assert settings.min_request_interval_seconds == 1.25


def test_blank_api_key_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WNBA_ENGINE_KALSHI_API_KEY", "")
    assert load_settings().kalshi_api_key is None


def test_settings_are_frozen(monkeypatch: pytest.MonkeyPatch):
    settings = load_settings()
    with pytest.raises(AttributeError):
        settings.database_url = "other"  # type: ignore[misc]
