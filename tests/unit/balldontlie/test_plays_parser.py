"""Unit tests for the balldontlie play-by-play parser.

Fixture (tests/fixtures/balldontlie_plays.json) is 5 real captured rows:
4 from a live API call (game 3858, 2025-05-16 Atlanta @ Washington), plus
1 "ejection" play (game 24830, 2026 season) that surfaced a real bug during
a live full-season backfill -- ejection plays carry text: null and no
"team" key at all, which crashed the original require_str-based parser.
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.balldontlie.plays_parser import parse_plays
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_plays_payload):
    plays = parse_plays(balldontlie_plays_payload)
    assert len(plays) == 5


def test_parses_jumpball_play(balldontlie_plays_payload):
    plays = parse_plays(balldontlie_plays_payload)
    jumpball = plays[0]
    assert jumpball.game.external_id == "3858"
    assert jumpball.team is not None
    assert jumpball.team.external_id == "4"
    assert jumpball.team.abbreviation == "ATL"
    assert jumpball.sequence == 1
    assert jumpball.period == 1
    assert jumpball.clock == "10:00"
    assert jumpball.play_type == "Jumpball"
    assert jumpball.description == (
        "Brittney Griner vs. Kiki Iriafen (Rhyne Howard gains possession)"
    )
    assert jumpball.home_score == 0
    assert jumpball.away_score == 0
    assert jumpball.scoring_play is False
    assert jumpball.score_value == 0


def test_parses_scoring_play(balldontlie_plays_payload):
    plays = parse_plays(balldontlie_plays_payload)
    three_pointer = plays[1]
    assert three_pointer.description == (
        "Rhyne Howard makes 23-foot three point jumper (Te-Hina Paopao assists)"
    )
    assert three_pointer.scoring_play is True
    assert three_pointer.score_value == 3
    assert three_pointer.away_score == 3


def test_rows_parse_independently_with_different_teams(balldontlie_plays_payload):
    plays = parse_plays(balldontlie_plays_payload)
    assert plays[2].team.abbreviation == "WSH"
    assert plays[3].team.abbreviation == "ATL"


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError):
        parse_plays({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_plays([])


def test_missing_required_field_raises(balldontlie_plays_payload):
    mutated = copy.deepcopy(balldontlie_plays_payload)
    del mutated["data"][0]["type"]
    with pytest.raises(ProviderValidationError):
        parse_plays(mutated)


def test_missing_team_becomes_none(balldontlie_plays_payload):
    mutated = copy.deepcopy(balldontlie_plays_payload)
    del mutated["data"][0]["team"]
    plays = parse_plays(mutated)
    assert plays[0].team is None


def test_ejection_play_with_null_text_and_no_team_parses(balldontlie_plays_payload):
    ejection = parse_plays(balldontlie_plays_payload)[4]
    assert ejection.play_type == "ejection"
    assert ejection.description is None
    assert ejection.team is None
    assert ejection.sequence == 293
    assert ejection.period == 3
