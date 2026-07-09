"""Unit tests for the balldontlie team advanced stats parser.

Fixture (tests/fixtures/balldontlie_team_advanced_stats.json) is 2 real
captured rows from a live API call to /wnba/v1/team_game_advanced_stats
(2025-05-16 Washington Mystics @ Atlanta Dream game) -- not hand-written
JSON.
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.balldontlie.team_advanced_stats_parser import parse_team_advanced_stats
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_team_advanced_stats_payload):
    stats = parse_team_advanced_stats(balldontlie_team_advanced_stats_payload)
    assert len(stats) == 2


def test_parses_team_game_refs(balldontlie_team_advanced_stats_payload):
    stats = parse_team_advanced_stats(balldontlie_team_advanced_stats_payload)
    mystics = stats[0]
    assert mystics.team.external_id == "5"
    assert mystics.team.abbreviation == "WSH"
    assert mystics.game.external_id == "3858"
    assert mystics.minutes == "200:00"


def test_parses_advanced_category_fields(balldontlie_team_advanced_stats_payload):
    stats = parse_team_advanced_stats(balldontlie_team_advanced_stats_payload)
    mystics = stats[0]
    assert mystics.offensive_rating == pytest.approx(119)
    assert mystics.defensive_rating == pytest.approx(113.9)
    assert mystics.net_rating == pytest.approx(5.1)
    assert mystics.pace == pytest.approx(94.8)
    assert mystics.possessions == 79
    assert mystics.true_shooting_percentage == pytest.approx(0.63)
    assert mystics.effective_field_goal_percentage == pytest.approx(0.582)
    assert mystics.usage_percentage == pytest.approx(1)
    assert mystics.assist_percentage == pytest.approx(0.581)
    assert mystics.assist_ratio == pytest.approx(17)
    assert mystics.assist_to_turnover == pytest.approx(2)
    assert mystics.turnover_ratio == pytest.approx(11.4)
    assert mystics.rebound_percentage == pytest.approx(0.422)
    assert mystics.offensive_rebound_percentage == pytest.approx(0.273)
    assert mystics.defensive_rebound_percentage == pytest.approx(0.52)
    assert mystics.pie == pytest.approx(0.558)


def test_parses_four_factors_fields(balldontlie_team_advanced_stats_payload):
    stats = parse_team_advanced_stats(balldontlie_team_advanced_stats_payload)
    mystics = stats[0]
    assert mystics.free_throw_attempt_rate == pytest.approx(0.508)
    assert mystics.team_turnover_percentage == pytest.approx(0.114)
    assert mystics.opp_effective_field_goal_percentage == pytest.approx(0.486)
    assert mystics.opp_free_throw_attempt_rate == pytest.approx(0.365)
    assert mystics.opp_team_turnover_percentage == pytest.approx(0.203)
    assert mystics.opp_offensive_rebound_percentage == pytest.approx(0.48)


def test_keeps_misc_usage_scoring_as_raw_dicts(balldontlie_team_advanced_stats_payload):
    stats = parse_team_advanced_stats(balldontlie_team_advanced_stats_payload)
    mystics = stats[0]
    assert mystics.misc_stats["blocks"] == 4
    assert mystics.misc_stats["points_paint"] == 36
    assert mystics.usage_stats["usage_percentage"] == pytest.approx(1)
    assert mystics.scoring_stats["percentage_points2pt"] == pytest.approx(0.468)


def test_second_row_parses_independently(balldontlie_team_advanced_stats_payload):
    stats = parse_team_advanced_stats(balldontlie_team_advanced_stats_payload)
    dream = stats[1]
    assert dream.team.abbreviation == "ATL"
    assert dream.offensive_rating == pytest.approx(113.9)
    assert dream.net_rating == pytest.approx(-5.1)


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_team_advanced_stats({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_team_advanced_stats(["not", "a", "dict"])


def test_missing_advanced_stats_block_raises(balldontlie_team_advanced_stats_payload):
    broken = copy.deepcopy(balldontlie_team_advanced_stats_payload)
    del broken["data"][0]["stats"]["advanced"]
    with pytest.raises(ProviderValidationError, match="advanced"):
        parse_team_advanced_stats(broken)


def test_null_numeric_field_becomes_none(balldontlie_team_advanced_stats_payload):
    payload = copy.deepcopy(balldontlie_team_advanced_stats_payload)
    payload["data"][0]["stats"]["advanced"]["possessions"] = None
    stats = parse_team_advanced_stats(payload)
    assert stats[0].possessions is None
