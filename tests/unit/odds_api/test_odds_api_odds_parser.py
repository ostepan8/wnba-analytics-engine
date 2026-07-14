"""Unit tests for the the-odds-api game-odds parser.

Fixtures (tests/fixtures/odds_api_current_odds.json,
tests/fixtures/odds_api_historical_odds.json) are trimmed from real
responses captured live from /v4/sports/basketball_wnba/odds/ and
/v4/historical/sports/basketball_wnba/odds/ (regions=us,
markets=h2h,spreads,totals, oddsFormat=american) -- not hand-written JSON.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.odds_api.odds_parser import (
    parse_current_odds,
    parse_current_odds_events,
    parse_historical_odds,
    parse_historical_odds_events,
)


def test_parses_one_row_per_bookmaker(odds_api_current_odds_payload):
    rows = parse_current_odds(odds_api_current_odds_payload)
    # 2 events x 2 bookmakers each = 4 rows
    assert len(rows) == 4


def test_parses_fanduel_row_for_first_event(odds_api_current_odds_payload):
    rows = parse_current_odds(odds_api_current_odds_payload)
    row = next(
        r
        for r in rows
        if r.game_external_id == "bbda183d9dc2a8ed43f79f82ef0ac320" and r.vendor == "fanduel"
    )
    assert row.external_id == "bbda183d9dc2a8ed43f79f82ef0ac320:fanduel"
    assert row.spread_home_value == pytest.approx(-11.5)
    assert row.spread_home_odds == -114
    assert row.spread_away_value == pytest.approx(11.5)
    assert row.spread_away_odds == -106
    assert row.moneyline_home_odds == -700
    assert row.moneyline_away_odds == 470
    assert row.total_value == pytest.approx(168.5)
    assert row.total_over_odds == -108
    assert row.total_under_odds == -112
    assert row.updated_at == datetime(2026, 7, 9, 20, 39, 38, tzinfo=UTC)


def test_home_away_assignment_uses_event_team_names_not_outcome_order(
    odds_api_current_odds_payload,
):
    # Second event's h2h outcomes list AWAY team (Las Vegas Aces) first --
    # home/away must resolve by matching outcome.name against
    # event.home_team/away_team, never by outcome list position.
    rows = parse_current_odds(odds_api_current_odds_payload)
    row = next(
        r
        for r in rows
        if r.game_external_id == "803d077d9e5f6f5b156f4a2be5ad2ec5" and r.vendor == "fanduel"
    )
    assert row.moneyline_home_odds == 300  # Portland Fire (home) is the underdog
    assert row.moneyline_away_odds == -400  # Las Vegas Aces (away) is favored


def test_external_id_distinguishes_bookmakers_within_same_event(odds_api_current_odds_payload):
    rows = parse_current_odds(odds_api_current_odds_payload)
    same_event = [r for r in rows if r.game_external_id == "bbda183d9dc2a8ed43f79f82ef0ac320"]
    assert len(same_event) == 2
    assert {r.external_id for r in same_event} == {
        "bbda183d9dc2a8ed43f79f82ef0ac320:fanduel",
        "bbda183d9dc2a8ed43f79f82ef0ac320:fanatics",
    }


def test_non_sequence_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_current_odds({"not": "a list"})


def test_event_missing_id_raises(odds_api_current_odds_payload):
    broken = copy.deepcopy(odds_api_current_odds_payload)
    del broken[0]["id"]
    with pytest.raises(ProviderValidationError, match="id"):
        parse_current_odds(broken)


def test_event_missing_home_team_raises(odds_api_current_odds_payload):
    broken = copy.deepcopy(odds_api_current_odds_payload)
    del broken[0]["home_team"]
    with pytest.raises(ProviderValidationError, match="home_team"):
        parse_current_odds(broken)


def test_event_with_no_bookmakers_key_yields_no_rows(odds_api_current_odds_payload):
    # Confirmed live: an event with no bookmakers list posted yet is a
    # legitimate (if rare) shape, not malformed data.
    broken = copy.deepcopy(odds_api_current_odds_payload)
    del broken[0]["bookmakers"]
    rows = parse_current_odds(broken)
    # only the second event's 2 bookmakers remain
    assert len(rows) == 2


def test_bookmaker_missing_last_update_raises(odds_api_current_odds_payload):
    broken = copy.deepcopy(odds_api_current_odds_payload)
    del broken[0]["bookmakers"][0]["last_update"]
    with pytest.raises(ProviderValidationError, match="last_update"):
        parse_current_odds(broken)


def test_unknown_market_key_ignored(odds_api_current_odds_payload):
    # Forward-compatible: a market type this schema doesn't map to
    # sportsbook_game_odds columns (e.g. 'alternate_spreads') should be
    # skipped, not crash the whole ingest.
    payload = copy.deepcopy(odds_api_current_odds_payload)
    payload[0]["bookmakers"][0]["markets"].append(
        {
            "key": "alternate_spreads",
            "last_update": "2026-07-09T20:39:38Z",
            "outcomes": [{"name": "Atlanta Dream", "price": -110, "point": -10.5}],
        }
    )
    rows = parse_current_odds(payload)
    row = next(
        r
        for r in rows
        if r.game_external_id == "bbda183d9dc2a8ed43f79f82ef0ac320" and r.vendor == "fanduel"
    )
    assert row.spread_home_value == pytest.approx(-11.5)  # unchanged by the extra market


def test_bookmaker_missing_a_market_leaves_those_fields_none(odds_api_current_odds_payload):
    # A bookmaker legitimately might not (yet) have posted every market.
    broken = copy.deepcopy(odds_api_current_odds_payload)
    broken[0]["bookmakers"][0]["markets"] = [
        m for m in broken[0]["bookmakers"][0]["markets"] if m["key"] != "totals"
    ]
    rows = parse_current_odds(broken)
    row = next(
        r
        for r in rows
        if r.game_external_id == "bbda183d9dc2a8ed43f79f82ef0ac320" and r.vendor == "fanduel"
    )
    assert row.total_value is None
    assert row.total_over_odds is None
    assert row.total_under_odds is None
    assert row.moneyline_home_odds == -700  # other markets unaffected


def test_parse_historical_odds_unwraps_data_key(odds_api_historical_odds_payload):
    rows = parse_historical_odds(odds_api_historical_odds_payload)
    assert len(rows) == 2  # 1 event x 2 bookmakers
    assert all(r.game_external_id == "cc2fc346e45b367f6fc79fdf44ab28ab" for r in rows)


def test_parse_historical_odds_missing_data_key_raises():
    with pytest.raises(ProviderValidationError, match="data"):
        parse_historical_odds({})


def test_parse_historical_odds_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_historical_odds(["not", "a", "dict"])


def test_parse_current_odds_events_carries_resolution_fields(odds_api_current_odds_payload):
    events = parse_current_odds_events(odds_api_current_odds_payload)
    assert len(events) == 2
    first = next(e for e in events if e.event.external_id == "bbda183d9dc2a8ed43f79f82ef0ac320")
    assert first.event.home_team == "Atlanta Dream"
    assert first.event.away_team == "Seattle Storm"
    assert first.event.commence_time == datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)
    assert len(first.rows) == 2


def test_parse_current_odds_events_keeps_event_with_no_bookmakers(odds_api_current_odds_payload):
    broken = copy.deepcopy(odds_api_current_odds_payload)
    del broken[0]["bookmakers"]
    events = parse_current_odds_events(broken)
    # the event itself is still resolvable even though it has no rows yet
    assert len(events) == 2
    empty = next(e for e in events if e.event.external_id == "bbda183d9dc2a8ed43f79f82ef0ac320")
    assert empty.rows == ()


def test_parse_current_odds_flattens_events(odds_api_current_odds_payload):
    events = parse_current_odds_events(odds_api_current_odds_payload)
    flat = parse_current_odds(odds_api_current_odds_payload)
    assert sum(len(e.rows) for e in events) == len(flat)


def test_parse_historical_odds_events_carries_resolution_fields(odds_api_historical_odds_payload):
    events = parse_historical_odds_events(odds_api_historical_odds_payload)
    assert len(events) == 1
    assert events[0].event.external_id == "cc2fc346e45b367f6fc79fdf44ab28ab"
    assert events[0].event.home_team == "Minnesota Lynx"
    assert events[0].event.away_team == "Connecticut Sun"
    assert len(events[0].rows) == 2
