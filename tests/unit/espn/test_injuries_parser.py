"""Unit tests for the ESPN injuries parser (pure, fixture-driven).

Fixture (tests/fixtures/espn_injuries.json) is a trimmed, real captured
response -- 2026-07-08, Atlanta Dream + Los Angeles Sparks, 2 injuries
each. Not hand-written JSON.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.espn.injuries_parser import parse_injuries

_CAPTURED_AT = datetime(2026, 7, 8, 23, 40, tzinfo=UTC)


def test_parses_all_entries(espn_injuries_payload):
    entries = parse_injuries(espn_injuries_payload, captured_at=_CAPTURED_AT)
    assert len(entries) == 4


def test_parses_player_and_team(espn_injuries_payload):
    entries = parse_injuries(espn_injuries_payload, captured_at=_CAPTURED_AT)
    plum = next(e for e in entries if e.player.full_name == "Kelsey Plum")
    assert plum.player.external_id == "3065570"
    assert plum.player.position == "G"
    assert plum.team.external_id == "6"
    assert plum.team.name == "Los Angeles Sparks"


def test_parses_status_and_injury_detail(espn_injuries_payload):
    entries = parse_injuries(espn_injuries_payload, captured_at=_CAPTURED_AT)
    plum = next(e for e in entries if e.player.full_name == "Kelsey Plum")
    assert plum.status == "Out"
    assert plum.status_type == "INJURY_STATUS_OUT"
    assert plum.injury_type == "Lower Leg"
    assert plum.side == "Left"
    assert plum.return_date == date(2026, 7, 28)
    assert plum.espn_injury_id == "32846"
    assert plum.reported_at == datetime(2026, 6, 24, 16, 5, tzinfo=UTC)
    assert plum.captured_at == _CAPTURED_AT
    assert "lower left leg injury" in plum.short_comment
    assert "brutal blow" in plum.long_comment


def test_entry_missing_optional_detail_fields_parses_as_none(espn_injuries_payload):
    payload = copy.deepcopy(espn_injuries_payload)
    entry = payload["injuries"][0]["injuries"][0]
    entry["details"] = {}
    entries = parse_injuries(payload, captured_at=_CAPTURED_AT)
    nye = next(e for e in entries if e.player.full_name == "Aaliyah Nye")
    assert nye.injury_type is None
    assert nye.side is None
    assert nye.return_date is None


def test_athlete_id_extracted_from_playercard_link(espn_injuries_payload):
    entries = parse_injuries(espn_injuries_payload, captured_at=_CAPTURED_AT)
    brink = next(e for e in entries if e.player.full_name == "Cameron Brink")
    assert brink.player.external_id == "4433404"


def test_missing_playercard_link_raises(espn_injuries_payload):
    payload = copy.deepcopy(espn_injuries_payload)
    payload["injuries"][0]["injuries"][0]["athlete"]["links"] = []
    with pytest.raises(ProviderValidationError, match="playercard"):
        parse_injuries(payload, captured_at=_CAPTURED_AT)


def test_empty_injuries_list_returns_nothing():
    assert parse_injuries({"injuries": []}, captured_at=_CAPTURED_AT) == ()


def test_missing_injuries_key_raises():
    with pytest.raises(ProviderValidationError, match="injuries"):
        parse_injuries({}, captured_at=_CAPTURED_AT)


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_injuries(["not", "a", "dict"], captured_at=_CAPTURED_AT)
