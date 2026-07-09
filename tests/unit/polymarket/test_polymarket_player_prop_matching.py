"""Unit tests for Polymarket player-prop title -> player name parsing."""

from __future__ import annotations

from wnba_engine.polymarket.player_prop_matching import parse_player_prop_name


def test_parses_real_captured_rebounds_prop():
    assert parse_player_prop_name("A'ja Wilson: Rebounds O/U 7.5") == "A'ja Wilson"


def test_parses_real_captured_points_prop():
    assert parse_player_prop_name("Aliyah Boston: Points O/U 14.5") == "Aliyah Boston"


def test_parses_real_captured_assists_prop():
    assert parse_player_prop_name("Aliyah Boston: Assists O/U 2.5") == "Aliyah Boston"


def test_team_matchup_title_returns_none():
    assert parse_player_prop_name("Atlanta Dream vs. Toronto Tempo") is None


def test_totals_title_with_colon_returns_none():
    result = parse_player_prop_name("Minnesota Lynx vs. Connecticut Sun: O/U 167.5")
    assert result is None


def test_spread_title_returns_none():
    assert parse_player_prop_name("Spread: Minnesota Lynx (-10.5)") is None


def test_futures_title_returns_none():
    assert parse_player_prop_name("Will A'ja Wilson win MVP?") is None
