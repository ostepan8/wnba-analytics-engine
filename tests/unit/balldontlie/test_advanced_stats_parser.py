"""Unit tests for the balldontlie player advanced stats parser.

Fixture (tests/fixtures/balldontlie_player_advanced_stats.json) is 2 real
captured rows from a live API call (2024-05-14 Washington Mystics game) --
not hand-written JSON.
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.balldontlie.advanced_stats_parser import parse_player_advanced_stats
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_player_advanced_stats_payload):
    stats = parse_player_advanced_stats(balldontlie_player_advanced_stats_payload)
    assert len(stats) == 2


def test_parses_player_team_game_refs(balldontlie_player_advanced_stats_payload):
    stats = parse_player_advanced_stats(balldontlie_player_advanced_stats_payload)
    samuelson = stats[0]
    assert samuelson.player.external_id == "541"
    assert samuelson.player.full_name == "Karlie Samuelson"
    assert samuelson.player.position == "G"
    # The top-level "team" (game context) is used, NOT the player's nested
    # current-roster team -- those can differ (trades) and the game-context
    # one is what actually happened in this game.
    assert samuelson.team.external_id == "5"
    assert samuelson.team.abbreviation == "WSH"
    assert samuelson.game.external_id == "3594"
    assert samuelson.minutes == "27:20"


def test_parses_advanced_category_fields(balldontlie_player_advanced_stats_payload):
    stats = parse_player_advanced_stats(balldontlie_player_advanced_stats_payload)
    samuelson = stats[0]
    assert samuelson.offensive_rating == pytest.approx(91.2)
    assert samuelson.defensive_rating == pytest.approx(89.3)
    assert samuelson.net_rating == pytest.approx(1.9)
    assert samuelson.pace == pytest.approx(99.23)
    assert samuelson.possessions == 57
    assert samuelson.true_shooting_percentage == pytest.approx(0.354)
    assert samuelson.effective_field_goal_percentage == pytest.approx(0.278)
    assert samuelson.usage_percentage == pytest.approx(0.194)
    assert samuelson.pie == pytest.approx(0.007)


def test_parses_four_factors_fields(balldontlie_player_advanced_stats_payload):
    stats = parse_player_advanced_stats(balldontlie_player_advanced_stats_payload)
    samuelson = stats[0]
    assert samuelson.free_throw_attempt_rate == pytest.approx(0.13)
    assert samuelson.team_turnover_percentage == pytest.approx(0.138)
    assert samuelson.opp_effective_field_goal_percentage == pytest.approx(0.449)


def test_keeps_misc_usage_scoring_as_raw_dicts(balldontlie_player_advanced_stats_payload):
    stats = parse_player_advanced_stats(balldontlie_player_advanced_stats_payload)
    samuelson = stats[0]
    assert samuelson.misc_stats["blocks"] == 0
    assert samuelson.usage_stats["usage_percentage"] == pytest.approx(0.194)
    assert samuelson.scoring_stats["percentage_points2pt"] == pytest.approx(0.286)


def test_second_row_parses_independently(balldontlie_player_advanced_stats_payload):
    stats = parse_player_advanced_stats(balldontlie_player_advanced_stats_payload)
    austin = stats[1]
    assert austin.player.full_name == "Shakira Austin"
    assert austin.offensive_rating == pytest.approx(109.3)


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_player_advanced_stats({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_player_advanced_stats(["not", "a", "dict"])


def test_missing_advanced_stats_block_raises(balldontlie_player_advanced_stats_payload):
    broken = copy.deepcopy(balldontlie_player_advanced_stats_payload)
    del broken["data"][0]["stats"]["advanced"]
    with pytest.raises(ProviderValidationError, match="advanced"):
        parse_player_advanced_stats(broken)


def test_null_numeric_field_becomes_none(balldontlie_player_advanced_stats_payload):
    payload = copy.deepcopy(balldontlie_player_advanced_stats_payload)
    payload["data"][0]["stats"]["advanced"]["possessions"] = None
    stats = parse_player_advanced_stats(payload)
    assert stats[0].possessions is None
