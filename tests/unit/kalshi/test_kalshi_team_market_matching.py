"""Unit tests for Kalshi team-level derivative-market ticker/title ->
(date, team[, team]) parsing (spreads, totals, quarter/half winners, OT).
"""

from __future__ import annotations

from datetime import date

from wnba_engine.kalshi.team_market_matching import (
    parse_single_team_market,
    parse_two_team_market,
)


def test_parses_real_captured_total_title():
    result = parse_two_team_market("KXWNBATOTAL-26JUL08INDLA", "Indiana vs Los Angeles")
    assert result == (date(2026, 7, 8), "Indiana", "Los Angeles")


def test_parses_real_captured_quarter_total_title():
    result = parse_two_team_market(
        "KXWNBA1QTOTAL-26JUL08GSTOR", "Golden State vs Toronto: 1st Quarter Total?"
    )
    assert result == (date(2026, 7, 8), "Golden State", "Toronto")


def test_parses_real_captured_quarter_winner_title():
    result = parse_two_team_market(
        "KXWNBA1QWINNER-26JUL08GSTOR", "Golden State vs Toronto: 1st Quarter Winner?"
    )
    assert result == (date(2026, 7, 8), "Golden State", "Toronto")


def test_parses_real_captured_quarter_spread_title():
    result = parse_two_team_market(
        "KXWNBA2QSPREAD-26JUL08GSTOR", "Golden State vs Toronto: 2nd Quarter by over 1.5 points?"
    )
    assert result == (date(2026, 7, 8), "Golden State", "Toronto")


def test_parses_real_captured_half_total_title():
    result = parse_two_team_market(
        "KXWNBA1HTOTAL-26JUL08GSTOR", "Golden State vs Toronto: First Half Total?"
    )
    assert result == (date(2026, 7, 8), "Golden State", "Toronto")


def test_parses_real_captured_half_winner_title():
    result = parse_two_team_market(
        "KXWNBA2HWINNER-26JUL08GSTOR", "Golden State vs Toronto: Second Half Winner?"
    )
    assert result == (date(2026, 7, 8), "Golden State", "Toronto")


def test_parses_real_captured_overtime_title():
    result = parse_two_team_market(
        "KXWNBAOT-26JUL08GSTOR", "Golden State vs Toronto on Jul 8, 2026: Overtime?"
    )
    assert result == (date(2026, 7, 8), "Golden State", "Toronto")


def test_two_team_matcher_rejects_single_team_spread_title():
    assert (
        parse_two_team_market("KXWNBASPREAD-26JUL08INDLA", "Indiana wins by over 7.5 points?")
        is None
    )


def test_parses_real_captured_full_game_spread_title():
    result = parse_single_team_market(
        "KXWNBASPREAD-26JUL08INDLA", "Indiana wins by over 7.5 points?"
    )
    assert result == (date(2026, 7, 8), "Indiana")


def test_parses_full_game_spread_title_without_trailing_question_mark():
    result = parse_single_team_market(
        "KXWNBASPREAD-26JUL08INDLA", "Los Angeles wins by over 12.5 points"
    )
    assert result == (date(2026, 7, 8), "Los Angeles")


def test_parses_real_captured_half_spread_title():
    result = parse_single_team_market(
        "KXWNBA2HSPREAD-26JUL09SEAATL", "Will Atlanta win the 2H by over 1.5 points?"
    )
    assert result == (date(2026, 7, 9), "Atlanta")


def test_single_team_matcher_rejects_two_team_total_title():
    assert parse_single_team_market("KXWNBATOTAL-26JUL08INDLA", "Indiana vs Los Angeles") is None


def test_season_long_award_market_returns_none_for_both_matchers():
    assert parse_two_team_market("KXWNBAMVP-26", "Will A'ja Wilson win MVP?") is None
    assert parse_single_team_market("KXWNBAMVP-26", "Will A'ja Wilson win MVP?") is None
