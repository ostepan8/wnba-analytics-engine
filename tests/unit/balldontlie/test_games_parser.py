"""Unit tests for the balldontlie games parser.

Fixture (tests/fixtures/balldontlie_games.json) is 2 real captured games
from a live API call -- not hand-written JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.balldontlie.games_parser import parse_games
from wnba_engine.errors import ProviderValidationError


def test_parses_all_games(balldontlie_games_payload):
    games = parse_games(balldontlie_games_payload)
    assert len(games) == 2


def test_parses_matchup_fields(balldontlie_games_payload):
    games = parse_games(balldontlie_games_payload)
    first = games[0]
    assert first.external_id == "3594"
    assert first.home_team_full_name == "Washington Mystics"
    assert first.away_team_full_name == "New York Liberty"
    assert first.start_time == datetime(2024, 5, 14, 23, 0, tzinfo=UTC)


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_games({})
