"""Unit tests for the balldontlie player-prop-odds parser.

Fixture (tests/fixtures/balldontlie_player_prop_odds.json) is trimmed from
the real response captured live from
/wnba/v1/odds/player_props?game_id=24909 -- 5 rows covering both market
shapes (milestone, over_under) and multiple prop_types -- not hand-written
JSON.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.balldontlie.player_prop_odds_parser import parse_player_prop_odds
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_player_prop_odds_payload):
    rows = parse_player_prop_odds(balldontlie_player_prop_odds_payload)
    assert len(rows) == 5


def test_parses_milestone_row(balldontlie_player_prop_odds_payload):
    rows = parse_player_prop_odds(balldontlie_player_prop_odds_payload)
    row = rows[0]
    assert row.external_id == "8663418827"
    assert row.game_external_id == "24909"
    assert row.player_external_id == "468"
    assert row.vendor == "betrivers"
    assert row.prop_type == "assists"
    assert row.line_value == pytest.approx(3.5)
    assert row.market_type == "milestone"
    assert row.odds == 107
    assert row.over_odds is None
    assert row.under_odds is None
    assert row.updated_at == datetime(2026, 7, 8, 0, 17, 10, 667000, tzinfo=UTC)


def test_parses_over_under_row(balldontlie_player_prop_odds_payload):
    rows = parse_player_prop_odds(balldontlie_player_prop_odds_payload)
    row = rows[1]
    assert row.player_external_id == "574"
    assert row.market_type == "over_under"
    assert row.odds is None
    assert row.over_odds == 115
    assert row.under_odds == -160
    assert row.line_value == pytest.approx(10.5)


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_player_prop_odds({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_player_prop_odds(["not", "a", "dict"])


def test_row_missing_player_id_raises(balldontlie_player_prop_odds_payload):
    broken = copy.deepcopy(balldontlie_player_prop_odds_payload)
    del broken["data"][0]["player_id"]
    with pytest.raises(ProviderValidationError, match="player_id"):
        parse_player_prop_odds(broken)


def test_row_missing_market_raises(balldontlie_player_prop_odds_payload):
    broken = copy.deepcopy(balldontlie_player_prop_odds_payload)
    del broken["data"][0]["market"]
    with pytest.raises(ProviderValidationError, match="market"):
        parse_player_prop_odds(broken)


def test_row_missing_market_type_raises(balldontlie_player_prop_odds_payload):
    broken = copy.deepcopy(balldontlie_player_prop_odds_payload)
    del broken["data"][0]["market"]["type"]
    with pytest.raises(ProviderValidationError, match="type"):
        parse_player_prop_odds(broken)


def test_row_unknown_market_type_raises(balldontlie_player_prop_odds_payload):
    broken = copy.deepcopy(balldontlie_player_prop_odds_payload)
    broken["data"][0]["market"] = {"type": "unheard_of_shape"}
    with pytest.raises(ProviderValidationError, match="unknown market.type"):
        parse_player_prop_odds(broken)


def test_row_missing_line_value_raises(balldontlie_player_prop_odds_payload):
    broken = copy.deepcopy(balldontlie_player_prop_odds_payload)
    del broken["data"][0]["line_value"]
    with pytest.raises(ProviderValidationError, match="line_value"):
        parse_player_prop_odds(broken)


def test_non_mapping_row_raises(balldontlie_player_prop_odds_payload):
    broken = copy.deepcopy(balldontlie_player_prop_odds_payload)
    broken["data"][0] = "not a dict"
    with pytest.raises(ProviderValidationError, match="row must be an object"):
        parse_player_prop_odds(broken)
