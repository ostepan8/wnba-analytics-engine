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
def espn_scoreboard_allstar_payload() -> object:
    return load_fixture("espn_scoreboard_allstar.json")


@pytest.fixture
def espn_summary_payload() -> object:
    return load_fixture("espn_summary.json")


@pytest.fixture
def espn_summary_with_game_info_payload() -> object:
    return load_fixture("espn_summary_with_game_info.json")


@pytest.fixture
def kalshi_series_payload() -> object:
    return load_fixture("kalshi_series.json")


@pytest.fixture
def kalshi_markets_payload() -> object:
    return load_fixture("kalshi_markets.json")


@pytest.fixture
def polymarket_events_payload() -> object:
    return load_fixture("polymarket_events.json")


@pytest.fixture
def espn_injuries_payload() -> object:
    return load_fixture("espn_injuries.json")


@pytest.fixture
def espn_transactions_2022_payload() -> object:
    return load_fixture("espn_transactions_2022.json")


@pytest.fixture
def espn_transactions_2025_page2_payload() -> object:
    return load_fixture("espn_transactions_2025_page2.json")


@pytest.fixture
def espn_wayback_injuries_html() -> str:
    return (FIXTURES_DIR / "espn_wayback_injuries.html").read_text()


@pytest.fixture
def balldontlie_player_advanced_stats_payload() -> object:
    return load_fixture("balldontlie_player_advanced_stats.json")


@pytest.fixture
def balldontlie_player_advanced_stats_bio_payload() -> object:
    return load_fixture("balldontlie_player_advanced_stats_bio.json")


@pytest.fixture
def balldontlie_team_advanced_stats_payload() -> object:
    return load_fixture("balldontlie_team_advanced_stats.json")


@pytest.fixture
def balldontlie_player_shot_zones_bio_payload() -> object:
    return load_fixture("balldontlie_player_shot_zones_bio.json")


@pytest.fixture
def balldontlie_games_payload() -> object:
    return load_fixture("balldontlie_games.json")


@pytest.fixture
def balldontlie_plays_payload() -> object:
    return load_fixture("balldontlie_plays.json")


@pytest.fixture
def balldontlie_player_shot_zones_payload() -> object:
    return load_fixture("balldontlie_player_shot_zones.json")


@pytest.fixture
def balldontlie_team_shot_zones_payload() -> object:
    return load_fixture("balldontlie_team_shot_zones.json")


@pytest.fixture
def balldontlie_standings_payload() -> object:
    return load_fixture("balldontlie_standings.json")


@pytest.fixture
def balldontlie_odds_payload() -> object:
    return load_fixture("balldontlie_odds.json")


@pytest.fixture
def balldontlie_player_prop_odds_payload() -> object:
    return load_fixture("balldontlie_player_prop_odds.json")


@pytest.fixture
def balldontlie_players_payload() -> object:
    return load_fixture("balldontlie_players.json")


@pytest.fixture
def balldontlie_player_stats_payload() -> object:
    return load_fixture("balldontlie_player_stats.json")


@pytest.fixture
def balldontlie_team_stats_payload() -> object:
    return load_fixture("balldontlie_team_stats.json")


@pytest.fixture
def balldontlie_player_injuries_payload() -> object:
    return load_fixture("balldontlie_player_injuries.json")
