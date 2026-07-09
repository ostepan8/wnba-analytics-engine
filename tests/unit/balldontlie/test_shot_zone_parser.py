"""Unit tests for the balldontlie shot-zone stats parser (season-level
zone efficiency splits, NOT per-shot x/y coordinates).

Fixtures (tests/fixtures/balldontlie_player_shot_zones.json,
balldontlie_team_shot_zones.json) are real captured rows from a live API
call (2025 season) -- not hand-written JSON.
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.balldontlie.shot_zone_parser import (
    parse_player_shot_zone_stats,
    parse_team_shot_zone_stats,
)
from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.shot_zones import ShotZoneCounts


def test_parses_player_row(balldontlie_player_shot_zones_payload):
    stats = parse_player_shot_zone_stats(balldontlie_player_shot_zones_payload)
    assert len(stats) == 1
    wilson = stats[0]
    assert wilson.player.external_id == "535"
    assert wilson.player.full_name == "A'ja Wilson"
    assert wilson.player.position == "C"
    assert wilson.team is not None
    assert wilson.team.abbreviation == "LV"
    assert wilson.season == 2025
    assert wilson.season_type == "regular"


def test_parses_player_zone_breakdown(balldontlie_player_shot_zones_payload):
    stats = parse_player_shot_zone_stats(balldontlie_player_shot_zones_payload)
    zones = stats[0].zones
    assert (zones.restricted_area.fga, zones.restricted_area.fgm) == (130, 91)
    assert (zones.mid_range.fga, zones.mid_range.fgm) == (146, 66)
    assert (zones.corner_3.fga, zones.corner_3.fgm) == (4, 2)
    assert (zones.left_corner_3.fga, zones.left_corner_3.fgm) == (1, 0)
    assert (zones.right_corner_3.fga, zones.right_corner_3.fgm) == (3, 2)
    assert (zones.above_the_break_3.fga, zones.above_the_break_3.fgm) == (55, 23)
    assert (zones.in_the_paint_non_ra.fga, zones.in_the_paint_non_ra.fgm) == (323, 150)
    assert (zones.backcourt.fga, zones.backcourt.fgm) == (0, 0)


def test_parses_team_row(balldontlie_team_shot_zones_payload):
    stats = parse_team_shot_zone_stats(balldontlie_team_shot_zones_payload)
    assert len(stats) == 1
    dream = stats[0]
    assert dream.team.external_id == "4"
    assert dream.team.abbreviation == "ATL"
    assert dream.season == 2025
    assert dream.season_type == "regular"
    assert (dream.zones.restricted_area.fga, dream.zones.restricted_area.fgm) == (939, 575)
    assert (dream.zones.backcourt.fga, dream.zones.backcourt.fgm) == (16, 0)


def test_missing_zone_becomes_none_counts(balldontlie_player_shot_zones_payload):
    mutated = copy.deepcopy(balldontlie_player_shot_zones_payload)
    del mutated["data"][0]["stats"]["shot_zones"]["backcourt"]
    stats = parse_player_shot_zone_stats(mutated)
    assert stats[0].zones.backcourt == ShotZoneCounts(fga=None, fgm=None)


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError):
        parse_player_shot_zone_stats({})
    with pytest.raises(ProviderValidationError):
        parse_team_shot_zone_stats({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_player_shot_zone_stats([])
    with pytest.raises(ProviderValidationError):
        parse_team_shot_zone_stats([])


def test_missing_shot_zones_block_raises(balldontlie_player_shot_zones_payload):
    mutated = copy.deepcopy(balldontlie_player_shot_zones_payload)
    del mutated["data"][0]["stats"]["shot_zones"]
    with pytest.raises(ProviderValidationError):
        parse_player_shot_zone_stats(mutated)


def test_parses_player_bio_fields(balldontlie_player_shot_zones_bio_payload):
    # Real fixture (tests/fixtures/balldontlie_player_shot_zones_bio.json):
    # A'ja Wilson has a full bio; Alexis Prince comes back with real JSON
    # null for height/weight/college/age (not the "--" placeholder), only
    # jersey_number populated -- confirms both null-shapes are handled.
    stats = parse_player_shot_zone_stats(balldontlie_player_shot_zones_bio_payload)
    wilson, prince = stats[0], stats[1]
    assert wilson.player.height == "6' 4\""
    assert wilson.player.weight == "195 lbs"
    assert wilson.player.jersey_number == "22"
    assert wilson.player.college == "South Carolina"
    assert wilson.player.age == 29

    assert prince.player.height is None
    assert prince.player.weight is None
    assert prince.player.jersey_number == "15"
    assert prince.player.college is None
    assert prince.player.age is None
