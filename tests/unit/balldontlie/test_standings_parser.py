"""Unit tests for the balldontlie standings parser.

Fixture (tests/fixtures/balldontlie_standings.json) is the real, full
season=2025 response captured live from /wnba/v1/standings -- 13 rows, one
per WNBA team -- not hand-written JSON.
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.balldontlie.standings_parser import parse_standings
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_standings_payload):
    rows = parse_standings(balldontlie_standings_payload)
    assert len(rows) == 13


def test_parses_first_row_team_and_record_fields(balldontlie_standings_payload):
    rows = parse_standings(balldontlie_standings_payload)
    atl = rows[0]
    assert atl.team.external_id == "4"
    assert atl.team.abbreviation == "ATL"
    assert atl.season == 2025
    assert atl.conference == "Eastern Conference"
    assert atl.wins == 30
    assert atl.losses == 14
    assert atl.win_percentage == pytest.approx(0.682)
    assert atl.games_behind == pytest.approx(0)
    assert atl.home_record == "16-6"
    assert atl.away_record == "14-8"
    assert atl.conference_record == "15-6"
    assert atl.playoff_seed == 1


def test_parses_western_conference_row_independently(balldontlie_standings_payload):
    rows = parse_standings(balldontlie_standings_payload)
    minnesota = next(r for r in rows if r.team.abbreviation == "MIN")
    assert minnesota.team.external_id == "7"
    assert minnesota.conference == "Western Conference"
    assert minnesota.wins == 34
    assert minnesota.losses == 10
    assert minnesota.win_percentage == pytest.approx(0.773)
    assert minnesota.games_behind == pytest.approx(0)
    assert minnesota.playoff_seed == 1


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_standings({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_standings(["not", "a", "dict"])


def test_row_missing_team_raises(balldontlie_standings_payload):
    broken = copy.deepcopy(balldontlie_standings_payload)
    del broken["data"][0]["team"]
    with pytest.raises(ProviderValidationError, match="team"):
        parse_standings(broken)


def test_row_missing_wins_raises(balldontlie_standings_payload):
    broken = copy.deepcopy(balldontlie_standings_payload)
    del broken["data"][0]["wins"]
    with pytest.raises(ProviderValidationError, match="wins"):
        parse_standings(broken)


def test_row_missing_home_record_raises(balldontlie_standings_payload):
    broken = copy.deepcopy(balldontlie_standings_payload)
    del broken["data"][0]["home_record"]
    with pytest.raises(ProviderValidationError, match="home_record"):
        parse_standings(broken)


def test_non_mapping_row_raises(balldontlie_standings_payload):
    broken = copy.deepcopy(balldontlie_standings_payload)
    broken["data"][0] = "not a dict"
    with pytest.raises(ProviderValidationError, match="row must be an object"):
        parse_standings(broken)
