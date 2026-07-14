"""Unit tests for the the-odds-api scores parser.

Fixture (tests/fixtures/odds_api_scores.json) is trimmed from the real
response captured live from /v4/sports/basketball_wnba/scores/?daysFrom=3
-- 3 completed games + 1 not-yet-started game (scores=null, completed=
false) -- not hand-written JSON.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.odds_api.scores_parser import parse_scores


def test_parses_only_completed_games(odds_api_scores_payload):
    rows = parse_scores(odds_api_scores_payload)
    # fixture has 3 completed + 1 not-yet-started -- the latter must be skipped
    assert len(rows) == 3


def test_parses_first_row_fields(odds_api_scores_payload):
    rows = parse_scores(odds_api_scores_payload)
    row = next(r for r in rows if r.external_id == "1fbe348b23c9f547e63ce18ccf0888db")
    assert row.home_team == "Washington Mystics"
    assert row.away_team == "Golden State Valkyries"
    assert row.home_score == 49
    assert row.away_score == 62
    assert row.commence_time == datetime(2026, 7, 6, 23, 32, 43, tzinfo=UTC)
    assert row.captured_at == datetime(2026, 7, 7, 9, 22, 48, tzinfo=UTC)


def test_non_sequence_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_scores({"not": "a list"})


def test_event_missing_home_team_raises(odds_api_scores_payload):
    broken = copy.deepcopy(odds_api_scores_payload)
    del broken[0]["home_team"]
    with pytest.raises(ProviderValidationError, match="home_team"):
        parse_scores(broken)


def test_completed_event_missing_scores_key_is_skipped(odds_api_scores_payload):
    # Observed live: not-yet-started events carry completed=false and
    # scores=null together, but treat a missing/null scores list as "not
    # ready yet" regardless of the completed flag, rather than crashing --
    # a partially-settled/corrected event is the provider's problem to fix
    # upstream, not ours to guess at.
    broken = copy.deepcopy(odds_api_scores_payload)
    broken[0]["scores"] = None
    rows = parse_scores(broken)
    assert not any(r.external_id == "1fbe348b23c9f547e63ce18ccf0888db" for r in rows)
    assert len(rows) == 2


def test_score_entry_not_matching_either_team_raises(odds_api_scores_payload):
    broken = copy.deepcopy(odds_api_scores_payload)
    broken[0]["scores"][0]["name"] = "Some Other Team"
    with pytest.raises(ProviderValidationError, match="did not match"):
        parse_scores(broken)


def test_non_mapping_event_raises(odds_api_scores_payload):
    broken = copy.deepcopy(odds_api_scores_payload)
    broken[0] = "not a dict"
    with pytest.raises(ProviderValidationError, match="event must be an object"):
        parse_scores(broken)
