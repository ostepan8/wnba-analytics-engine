"""Unit tests for the ESPN summary (box score) parser."""

from __future__ import annotations

import copy

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.espn.parser import parse_summary


def test_parses_game_id_and_both_teams(espn_summary_payload):
    box = parse_summary(espn_summary_payload)
    assert box.game_external_id == "401736228"
    assert len(box.teams) == 2
    assert {t.team.abbreviation for t in box.teams} == {"SEA", "NY"}


def test_team_totals(espn_summary_payload):
    box = parse_summary(espn_summary_payload)
    sea = next(t for t in box.teams if t.team.abbreviation == "SEA")
    assert sea.team.external_id == "14"
    assert sea.field_goals.made == 32
    assert sea.field_goals.attempted == 71
    assert sea.three_pointers.made == 5
    assert sea.three_pointers.attempted == 17
    assert sea.free_throws.made == 10
    assert sea.free_throws.attempted == 14
    assert sea.rebounds == 35
    assert sea.offensive_rebounds == 8
    assert sea.defensive_rebounds == 27
    assert sea.assists == 21
    assert sea.steals == 11
    assert sea.blocks == 6
    assert sea.turnovers == 10
    assert sea.fouls == 14


def test_player_lines(espn_summary_payload):
    box = parse_summary(espn_summary_payload)
    ogwumike = next(p for p in box.players if p.player.external_id == "1068")
    assert ogwumike.player.full_name == "Nneka Ogwumike"
    assert ogwumike.player.position == "F"
    assert ogwumike.team.external_id == "14"
    assert ogwumike.starter is True
    assert ogwumike.did_not_play is False
    assert ogwumike.minutes == 35
    assert ogwumike.points == 15
    assert ogwumike.field_goals.made == 7
    assert ogwumike.field_goals.attempted == 13
    assert ogwumike.three_pointers.made == 0
    assert ogwumike.three_pointers.attempted == 1
    assert ogwumike.free_throws.made == 1
    assert ogwumike.free_throws.attempted == 1
    assert ogwumike.rebounds == 7
    assert ogwumike.assists == 4
    assert ogwumike.turnovers == 1
    assert ogwumike.steals == 1
    assert ogwumike.blocks == 0
    assert ogwumike.offensive_rebounds == 1
    assert ogwumike.defensive_rebounds == 6
    assert ogwumike.fouls == 2
    assert ogwumike.plus_minus == 8


def test_did_not_play_player_has_no_stats(espn_summary_payload):
    box = parse_summary(espn_summary_payload)
    dnp = next(p for p in box.players if p.player.external_id == "3917453")
    assert dnp.player.full_name == "Katie Lou Samuelson"
    assert dnp.did_not_play is True
    assert dnp.minutes is None
    assert dnp.points is None
    assert dnp.field_goals is None
    assert dnp.plus_minus is None


def test_negative_plus_minus_parses(espn_summary_payload):
    payload = copy.deepcopy(espn_summary_payload)
    athlete = payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]
    athlete["stats"][-1] = "-12"
    box = parse_summary(payload)
    line = next(p for p in box.players if p.player.external_id == "1068")
    assert line.plus_minus == -12


def test_missing_boxscore_raises():
    with pytest.raises(ProviderValidationError, match="boxscore"):
        parse_summary({"header": {"id": "x"}})


def test_stats_labels_mismatch_raises(espn_summary_payload):
    broken = copy.deepcopy(espn_summary_payload)
    stats_block = broken["boxscore"]["players"][0]["statistics"][0]
    stats_block["labels"] = stats_block["labels"][:-1]
    with pytest.raises(ProviderValidationError, match="labels"):
        parse_summary(broken)


def test_missing_team_statistic_raises(espn_summary_payload):
    broken = copy.deepcopy(espn_summary_payload)
    team_stats = broken["boxscore"]["teams"][0]["statistics"]
    broken["boxscore"]["teams"][0]["statistics"] = [
        s for s in team_stats if s["name"] != "totalRebounds"
    ]
    with pytest.raises(ProviderValidationError, match="totalRebounds"):
        parse_summary(broken)
