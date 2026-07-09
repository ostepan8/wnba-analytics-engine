"""Unit tests for Polymarket team-level derivative-market title parsing
(spread, total) -- the colon-containing shapes game_matching.py's
parse_matchup_teams deliberately excludes.
"""

from __future__ import annotations

from wnba_engine.polymarket.team_market_matching import (
    parse_spread_market_team,
    parse_total_market_teams,
)


def test_parses_real_captured_total_title():
    result = parse_total_market_teams("Golden State Valkyries vs. Toronto Tempo: O/U 165.5")
    assert result == ("Golden State Valkyries", "Toronto Tempo")


def test_parses_real_captured_spread_title():
    assert parse_spread_market_team("Spread: Atlanta Dream (-10.5)") == "Atlanta Dream"


def test_parses_spread_title_with_positive_line():
    assert parse_spread_market_team("Spread: Dallas Wings (+6.5)") == "Dallas Wings"


def test_player_prop_title_returns_none_for_both():
    assert parse_total_market_teams("A'ja Wilson: Rebounds O/U 7.5") is None
    assert parse_spread_market_team("A'ja Wilson: Rebounds O/U 7.5") is None


def test_futures_title_returns_none_for_both():
    title = "Will Atlanta Dream win the 2026 WNBA Finals?"
    assert parse_total_market_teams(title) is None
    assert parse_spread_market_team(title) is None


def test_total_matcher_rejects_spread_title():
    assert parse_total_market_teams("Spread: Atlanta Dream (-10.5)") is None


def test_spread_matcher_rejects_total_title():
    title = "Golden State Valkyries vs. Toronto Tempo: O/U 165.5"
    assert parse_spread_market_team(title) is None
