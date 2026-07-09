"""Unit tests for the balldontlie player_injuries parser.

Fixture (tests/fixtures/balldontlie_player_injuries.json) is real data
captured live from /wnba/v1/player_injuries and trimmed to 3 rows -- one
"Out" with a comment, one "Day-To-Day", and one "Out" with comment=null
(verified live: 2 of 43 real rows had a null comment) -- not hand-written
JSON.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.balldontlie.injuries_parser import parse_injuries
from wnba_engine.errors import ProviderValidationError

CAPTURED_AT = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def test_parses_all_rows(balldontlie_player_injuries_payload):
    entries = parse_injuries(balldontlie_player_injuries_payload, captured_at=CAPTURED_AT)
    assert len(entries) == 3


def test_parses_first_row_player_team_and_status_fields(balldontlie_player_injuries_payload):
    entries = parse_injuries(balldontlie_player_injuries_payload, captured_at=CAPTURED_AT)
    nye = entries[0]
    assert nye.player.external_id == "750"
    assert nye.player.full_name == "Aaliyah Nye"
    assert nye.player.position == "G"
    assert nye.player.college == "Alabama"
    assert nye.player.weight is None  # "--" placeholder -> None, same as other balldontlie bio
    assert nye.team.external_id == "4"
    assert nye.team.abbreviation == "ATL"
    assert nye.status == "Out"
    assert nye.return_date_text == "Jul 9"
    assert nye.comment == "Jul 8: Nye (knee) is questionable for Thursday's game against the Storm."
    assert nye.captured_at == CAPTURED_AT


def test_parses_row_with_null_comment(balldontlie_player_injuries_payload):
    entries = parse_injuries(balldontlie_player_injuries_payload, captured_at=CAPTURED_AT)
    sabally = next(e for e in entries if e.player.full_name == "Satou Sabally")
    assert sabally.comment is None
    assert sabally.status == "Out"
    assert sabally.return_date_text == "Jul 11"
    assert sabally.team.abbreviation == "NY"


def test_parses_day_to_day_status(balldontlie_player_injuries_payload):
    entries = parse_injuries(balldontlie_player_injuries_payload, captured_at=CAPTURED_AT)
    thomas = next(e for e in entries if e.player.full_name == "Alyssa Thomas")
    assert thomas.status == "Day-To-Day"
    assert thomas.team.abbreviation == "PHX"


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_injuries({}, captured_at=CAPTURED_AT)


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_injuries(["not", "a", "dict"], captured_at=CAPTURED_AT)


def test_non_mapping_row_raises(balldontlie_player_injuries_payload):
    broken = copy.deepcopy(balldontlie_player_injuries_payload)
    broken["data"][0] = "not a dict"
    with pytest.raises(ProviderValidationError, match="row must be an object"):
        parse_injuries(broken, captured_at=CAPTURED_AT)


def test_row_missing_status_raises(balldontlie_player_injuries_payload):
    broken = copy.deepcopy(balldontlie_player_injuries_payload)
    del broken["data"][0]["status"]
    with pytest.raises(ProviderValidationError, match="status"):
        parse_injuries(broken, captured_at=CAPTURED_AT)


def test_row_missing_player_raises(balldontlie_player_injuries_payload):
    broken = copy.deepcopy(balldontlie_player_injuries_payload)
    del broken["data"][0]["player"]
    with pytest.raises(ProviderValidationError, match="player"):
        parse_injuries(broken, captured_at=CAPTURED_AT)


def test_row_missing_team_raises(balldontlie_player_injuries_payload):
    broken = copy.deepcopy(balldontlie_player_injuries_payload)
    del broken["data"][0]["player"]["team"]
    with pytest.raises(ProviderValidationError, match="team"):
        parse_injuries(broken, captured_at=CAPTURED_AT)
