"""Unit tests for KXWNBAGAME ticker/title -> (date, team, team) parsing."""

from __future__ import annotations

from datetime import date

from wnba_engine.kalshi.game_matching import parse_matchup


def test_parses_real_captured_ticker_and_title():
    result = parse_matchup("KXWNBAGAME-26JUL09INDPHX", "Indiana vs Phoenix winner?")
    assert result == (date(2026, 7, 9), "Indiana", "Phoenix")


def test_non_game_series_returns_none():
    assert parse_matchup("KXWNBATOTAL-26", "Total points over 165.5?") is None


def test_malformed_title_returns_none():
    assert parse_matchup("KXWNBAGAME-26JUL09INDPHX", "Indiana beats Phoenix") is None


def test_unknown_month_abbreviation_returns_none():
    assert parse_matchup("KXWNBAGAME-26XXX09INDPHX", "Indiana vs Phoenix winner?") is None


def test_invalid_calendar_date_returns_none():
    assert parse_matchup("KXWNBAGAME-26FEB30INDPHX", "Indiana vs Phoenix winner?") is None
