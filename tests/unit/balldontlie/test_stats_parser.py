"""Unit tests for the balldontlie traditional box score stats parser.

Fixtures (tests/fixtures/balldontlie_player_stats.json,
balldontlie_team_stats.json) are real rows captured live from
/wnba/v1/player_stats and /wnba/v1/team_stats for game 3858 (Atlanta Dream
@ Washington Mystics, 2025-05-16) -- not hand-written JSON. Player stats
deliberately include three real shapes: a normal played row with some
untracked fields (Sonia Citron), a low-minute row where most counting
stats come back null even though the player logged minutes (Naz Hillmon,
min="2"), and a genuine did-not-play row (Taylor Thierry, min="0", every
stat null).
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.balldontlie.stats_parser import parse_player_stats, parse_team_stats
from wnba_engine.errors import ProviderValidationError


def test_parses_all_player_rows(balldontlie_player_stats_payload):
    rows = parse_player_stats(balldontlie_player_stats_payload)
    assert len(rows) == 3


def test_parses_player_identity_and_refs(balldontlie_player_stats_payload):
    rows = parse_player_stats(balldontlie_player_stats_payload)
    citron = rows[0]
    assert citron.player.external_id == "736"
    assert citron.player.full_name == "Sonia Citron"
    assert citron.player.position == "G"
    assert citron.player.college == "Notre Dame"
    assert citron.player.jersey_number == "22"
    assert citron.player.weight is None  # real "--" placeholder
    assert citron.team.external_id == "5"
    assert citron.team.abbreviation == "WSH"
    assert citron.game.external_id == "3858"


def test_parses_played_row_box_line(balldontlie_player_stats_payload):
    rows = parse_player_stats(balldontlie_player_stats_payload)
    citron = rows[0]
    assert citron.box.did_not_play is False
    assert citron.box.minutes == 24
    assert citron.box.points == 19
    assert citron.box.field_goals.made == 6
    assert citron.box.field_goals.attempted == 7
    assert citron.box.three_pointers.made == 2
    assert citron.box.three_pointers.attempted == 2
    assert citron.box.free_throws.made == 5
    assert citron.box.free_throws.attempted == 6
    assert citron.box.defensive_rebounds == 2
    assert citron.box.rebounds == 2
    assert citron.box.assists == 2
    assert citron.box.turnovers == 1
    assert citron.box.fouls == 4
    assert citron.box.plus_minus == 3
    # Real balldontlie nulls for this row: oreb, stl, blk untracked.
    assert citron.box.offensive_rebounds is None
    assert citron.box.steals is None
    assert citron.box.blocks is None
    # balldontlie's traditional stats endpoint has no starter flag at all
    # (verified live) -- always False, a documented limitation.
    assert citron.box.starter is False


def test_low_minute_row_with_partial_null_shooting_is_not_did_not_play(
    balldontlie_player_stats_payload,
):
    rows = parse_player_stats(balldontlie_player_stats_payload)
    hillmon = rows[1]
    assert hillmon.player.full_name == "Naz Hillmon"
    assert hillmon.box.did_not_play is False
    assert hillmon.box.minutes == 2
    assert hillmon.box.plus_minus == -2
    # fgm is null while fga=1 is real -- an untracked-pair, collapsed to
    # None rather than fabricating a made value (same convention ESPN's
    # '--' placeholder uses for an untracked shooting line).
    assert hillmon.box.field_goals is None
    assert hillmon.box.three_pointers is None
    assert hillmon.box.points is None


def test_zero_minute_row_is_did_not_play(balldontlie_player_stats_payload):
    rows = parse_player_stats(balldontlie_player_stats_payload)
    thierry = rows[2]
    assert thierry.player.full_name == "Taylor Thierry"
    assert thierry.box.did_not_play is True
    assert thierry.box.minutes is None
    assert thierry.box.points is None
    assert thierry.box.field_goals is None


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_player_stats({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_player_stats(["not", "a", "dict"])


def test_missing_player_key_raises(balldontlie_player_stats_payload):
    broken = copy.deepcopy(balldontlie_player_stats_payload)
    del broken["data"][0]["player"]
    with pytest.raises(ProviderValidationError, match="player"):
        parse_player_stats(broken)


def test_parses_all_team_rows(balldontlie_team_stats_payload):
    rows = parse_team_stats(balldontlie_team_stats_payload)
    assert len(rows) == 2


def test_parses_team_identity_and_box(balldontlie_team_stats_payload):
    rows = parse_team_stats(balldontlie_team_stats_payload)
    atl = rows[0]
    assert atl.team.external_id == "4"
    assert atl.team.abbreviation == "ATL"
    assert atl.game.external_id == "3858"
    assert atl.box.field_goals.made == 30
    assert atl.box.field_goals.attempted == 74
    assert atl.box.three_pointers.made == 12
    assert atl.box.three_pointers.attempted == 36
    assert atl.box.free_throws.made == 18
    assert atl.box.free_throws.attempted == 27
    assert atl.box.rebounds == 37
    assert atl.box.offensive_rebounds == 15
    assert atl.box.defensive_rebounds == 22
    assert atl.box.assists == 24
    assert atl.box.steals == 4
    assert atl.box.blocks == 2
    assert atl.box.turnovers == 14
    assert atl.box.fouls == 22


def test_second_team_row_parses_independently(balldontlie_team_stats_payload):
    rows = parse_team_stats(balldontlie_team_stats_payload)
    wsh = rows[1]
    assert wsh.team.abbreviation == "WSH"
    assert wsh.box.field_goals.made == 31
    assert wsh.box.turnovers == 7


def test_team_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_team_stats({})
