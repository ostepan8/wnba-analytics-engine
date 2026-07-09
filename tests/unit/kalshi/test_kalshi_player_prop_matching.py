"""Unit tests for per-game player-prop ticker/title -> (date, player name)
parsing (KXWNBAPTS/REB/AST/3PT, ...).
"""

from __future__ import annotations

from datetime import date

from wnba_engine.kalshi.player_prop_matching import parse_player_prop


def test_parses_real_captured_points_prop():
    result = parse_player_prop("KXWNBAPTS-26JUL08GSTOR", "A'ja Wilson: 20+ points")
    assert result == (date(2026, 7, 8), "A'ja Wilson")


def test_parses_real_captured_rebounds_prop():
    result = parse_player_prop("KXWNBAREB-26JUL09INDPHX", "A'ja Wilson: 10+ rebounds")
    assert result == (date(2026, 7, 9), "A'ja Wilson")


def test_parses_real_captured_threes_prop():
    result = parse_player_prop("KXWNBA3PT-26JUL09GSTOR", "Natisha Hiedeman: 2+ threes")
    assert result == (date(2026, 7, 9), "Natisha Hiedeman")


def test_parses_real_captured_assists_prop():
    result = parse_player_prop("KXWNBAAST-26JUL09INDPHX", "Alyssa Thomas: 3+ assists")
    assert result == (date(2026, 7, 9), "Alyssa Thomas")


def test_season_long_award_market_returns_none():
    assert parse_player_prop("KXWNBAMVP-26", "Will A'ja Wilson win MVP?") is None


def test_team_spread_market_returns_none():
    result = parse_player_prop("KXWNBASPREAD-26JUL09INDPHX", "Indiana wins by over 1.5 points?")
    assert result is None


def test_team_total_market_returns_none():
    assert parse_player_prop("KXWNBATOTAL-26JUL09INDPHX", "Indiana vs Phoenix") is None


def test_unknown_month_abbreviation_returns_none():
    assert parse_player_prop("KXWNBAPTS-26XXX09GSTOR", "A'ja Wilson: 20+ points") is None


def test_invalid_calendar_date_returns_none():
    assert parse_player_prop("KXWNBAPTS-26FEB30GSTOR", "A'ja Wilson: 20+ points") is None
