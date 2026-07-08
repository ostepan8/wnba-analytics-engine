"""Shared test helpers: fixture loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def espn_scoreboard_payload() -> object:
    return load_fixture("espn_scoreboard.json")


@pytest.fixture
def espn_summary_payload() -> object:
    return load_fixture("espn_summary.json")


@pytest.fixture
def kalshi_series_payload() -> object:
    return load_fixture("kalshi_series.json")


@pytest.fixture
def kalshi_markets_payload() -> object:
    return load_fixture("kalshi_markets.json")


@pytest.fixture
def polymarket_events_payload() -> object:
    return load_fixture("polymarket_events.json")
