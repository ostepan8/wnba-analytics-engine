"""Unit tests for the balldontlie game-odds parser.

Fixture (tests/fixtures/balldontlie_odds.json) is trimmed from the real
response captured live from /wnba/v1/odds?dates[]=2026-07-08 -- 4 rows
across 2 games/3 vendors -- not hand-written JSON.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.balldontlie.odds_parser import parse_game_odds
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_odds_payload):
    rows = parse_game_odds(balldontlie_odds_payload)
    assert len(rows) == 4


def test_parses_draftkings_row_fields(balldontlie_odds_payload):
    rows = parse_game_odds(balldontlie_odds_payload)
    row = rows[0]
    assert row.external_id == "266605323"
    assert row.game_external_id == "24909"
    assert row.vendor == "draftkings"
    assert row.spread_home_value == pytest.approx(8.5)
    assert row.spread_home_odds == 105
    assert row.spread_away_value == pytest.approx(-8.5)
    assert row.spread_away_odds == -135
    assert row.moneyline_home_odds == 900
    assert row.moneyline_away_odds == -1850
    assert row.total_value == pytest.approx(166.5)
    assert row.total_over_odds == -110
    assert row.total_under_odds == -120
    assert row.updated_at == datetime(2026, 7, 8, 1, 59, 2, 636000, tzinfo=UTC)


def test_parses_second_game_row(balldontlie_odds_payload):
    rows = parse_game_odds(balldontlie_odds_payload)
    other_game_row = next(r for r in rows if r.game_external_id == "24910")
    assert other_game_row.vendor == "draftkings"
    assert other_game_row.moneyline_home_odds == 8000
    assert other_game_row.moneyline_away_odds == -100000


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_game_odds({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_game_odds(["not", "a", "dict"])


def test_row_missing_vendor_raises(balldontlie_odds_payload):
    broken = copy.deepcopy(balldontlie_odds_payload)
    del broken["data"][0]["vendor"]
    with pytest.raises(ProviderValidationError, match="vendor"):
        parse_game_odds(broken)


def test_row_missing_game_id_raises(balldontlie_odds_payload):
    broken = copy.deepcopy(balldontlie_odds_payload)
    del broken["data"][0]["game_id"]
    with pytest.raises(ProviderValidationError, match="game_id"):
        parse_game_odds(broken)


def test_row_missing_updated_at_raises(balldontlie_odds_payload):
    broken = copy.deepcopy(balldontlie_odds_payload)
    del broken["data"][0]["updated_at"]
    with pytest.raises(ProviderValidationError, match="updated_at"):
        parse_game_odds(broken)


def test_non_mapping_row_raises(balldontlie_odds_payload):
    broken = copy.deepcopy(balldontlie_odds_payload)
    broken["data"][0] = "not a dict"
    with pytest.raises(ProviderValidationError, match="row must be an object"):
        parse_game_odds(broken)


def test_row_with_null_spread_treated_as_none(balldontlie_odds_payload):
    # Not observed live (every real row had every field populated), but a
    # bookmaker legitimately might not quote every market for every game --
    # optional_float/optional_int must tolerate that rather than crash.
    row = copy.deepcopy(balldontlie_odds_payload["data"][0])
    row["spread_home_value"] = None
    row["spread_home_odds"] = None
    (parsed,) = parse_game_odds({"data": [row]})
    assert parsed.spread_home_value is None
    assert parsed.spread_home_odds is None
