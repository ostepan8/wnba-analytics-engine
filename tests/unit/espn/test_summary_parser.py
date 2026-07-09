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


def test_dash_placeholder_stat_becomes_none(espn_summary_payload):
    """ESPN occasionally returns '--' for a stat on a player marked as played
    (didNotPlay=False) rather than omitting it. Observed live during the
    2022-2026 historical backfill (24/1307 games) — one such field must not
    abort the whole game's box score.
    """
    payload = copy.deepcopy(espn_summary_payload)
    athlete = payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]
    athlete["stats"][-1] = "--"  # +/-, last in EXPECTED_PLAYER_LABELS
    box = parse_summary(payload)
    line = next(p for p in box.players if p.player.external_id == "1068")
    assert line.did_not_play is False
    assert line.points == 15  # other stats on the same line still parse
    assert line.plus_minus is None


def test_dash_placeholder_shooting_stat_becomes_none(espn_summary_payload):
    payload = copy.deepcopy(espn_summary_payload)
    athlete = payload["boxscore"]["players"][0]["statistics"][0]["athletes"][0]
    fg_index = payload["boxscore"]["players"][0]["statistics"][0]["labels"].index("FG")
    athlete["stats"][fg_index] = "--"
    box = parse_summary(payload)
    line = next(p for p in box.players if p.player.external_id == "1068")
    assert line.field_goals is None
    assert line.points == 15


def test_missing_boxscore_raises():
    with pytest.raises(ProviderValidationError, match="boxscore"):
        parse_summary({"header": {"id": "x"}})


def test_venue_and_attendance_parsed_from_game_info(espn_summary_with_game_info_payload):
    box = parse_summary(espn_summary_with_game_info_payload)
    assert box.venue_name == "Mohegan Sun Arena"
    assert box.attendance == 7508


def test_missing_game_info_leaves_venue_and_attendance_none(espn_summary_payload):
    """espn_summary.json (the original fixture) has no gameInfo key at all --
    parse_summary must fail open rather than raise, since gameInfo is new
    and optional data, not part of the original required payload shape.
    """
    assert "gameInfo" not in espn_summary_payload
    box = parse_summary(espn_summary_payload)
    assert box.venue_name is None
    assert box.attendance is None


def test_game_info_present_but_venue_missing_leaves_venue_none(
    espn_summary_with_game_info_payload,
):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    del payload["gameInfo"]["venue"]
    box = parse_summary(payload)
    assert box.venue_name is None
    assert box.attendance == 7508


def test_game_info_present_but_attendance_missing_leaves_attendance_none(
    espn_summary_with_game_info_payload,
):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    del payload["gameInfo"]["attendance"]
    box = parse_summary(payload)
    assert box.venue_name == "Mohegan Sun Arena"
    assert box.attendance is None


def test_game_info_not_a_mapping_fails_open(espn_summary_with_game_info_payload):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    payload["gameInfo"] = "unexpected string shape"
    box = parse_summary(payload)
    assert box.venue_name is None
    assert box.attendance is None


def test_officials_parsed_from_game_info(espn_summary_with_game_info_payload):
    box = parse_summary(espn_summary_with_game_info_payload)
    assert len(box.officials) == 3
    names = [o.name for o in box.officials]
    assert names == ["Tiara Cruse", "Paul Tuomey", "Catherine Chang"]
    for official, expected_order in zip(box.officials, (1, 2, 3), strict=True):
        assert official.role == "Referee"
        assert official.order == expected_order


def test_missing_game_info_leaves_officials_empty(espn_summary_payload):
    """espn_summary.json (the original fixture) has no gameInfo key at all --
    parse_summary must fail open to an empty officials tuple, not raise.
    """
    assert "gameInfo" not in espn_summary_payload
    box = parse_summary(espn_summary_payload)
    assert box.officials == ()


def test_game_info_present_but_officials_missing_leaves_officials_empty(
    espn_summary_with_game_info_payload,
):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    del payload["gameInfo"]["officials"]
    box = parse_summary(payload)
    assert box.officials == ()
    # venue/attendance still parse fine -- one missing sub-field must not
    # affect the others.
    assert box.venue_name == "Mohegan Sun Arena"
    assert box.attendance == 7508


def test_officials_not_a_list_fails_open(espn_summary_with_game_info_payload):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    payload["gameInfo"]["officials"] = "unexpected string shape"
    box = parse_summary(payload)
    assert box.officials == ()


def test_official_entry_missing_name_is_skipped(espn_summary_with_game_info_payload):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    del payload["gameInfo"]["officials"][1]["fullName"]
    box = parse_summary(payload)
    assert len(box.officials) == 2
    assert [o.name for o in box.officials] == ["Tiara Cruse", "Catherine Chang"]


def test_official_entry_missing_position_leaves_role_none(espn_summary_with_game_info_payload):
    payload = copy.deepcopy(espn_summary_with_game_info_payload)
    del payload["gameInfo"]["officials"][0]["position"]
    box = parse_summary(payload)
    first = next(o for o in box.officials if o.name == "Tiara Cruse")
    assert first.role is None
    assert first.order == 1


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
