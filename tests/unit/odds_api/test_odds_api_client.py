"""Unit test for OddsApiClient's fail-fast construction contract -- mirrors
BalldontlieClient's same guard (no free/anonymous tier, so a missing key is
a configuration error to catch immediately, not a transient failure to
retry into). client.py's HTTP behavior itself isn't unit tested here, same
convention as the other provider clients in this repo (thin wrappers,
smoke-tested live instead).
"""

from __future__ import annotations

import pytest

from wnba_engine.config import load_settings
from wnba_engine.odds_api.client import OddsApiClient


def test_missing_api_key_raises_at_construction(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WNBA_ENGINE_ODDS_API_KEY", raising=False)
    settings = load_settings()
    with pytest.raises(ValueError, match="WNBA_ENGINE_ODDS_API_KEY"):
        OddsApiClient(settings)


def test_present_api_key_constructs_successfully(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WNBA_ENGINE_ODDS_API_KEY", "test-key")
    settings = load_settings()
    client = OddsApiClient(settings)
    client.close()
