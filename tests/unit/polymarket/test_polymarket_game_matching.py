"""Unit tests for Polymarket team-matchup title parsing."""

from __future__ import annotations

from wnba_engine.polymarket.game_matching import parse_matchup_teams


def test_parses_real_captured_matchup_title():
    result = parse_matchup_teams("Atlanta Dream vs. Toronto Tempo")
    assert result == ("Atlanta Dream", "Toronto Tempo")


def test_matchup_without_period_also_parses():
    assert parse_matchup_teams("Seattle Storm vs New York Liberty") == (
        "Seattle Storm",
        "New York Liberty",
    )


def test_player_prop_title_returns_none():
    assert parse_matchup_teams("Aliyah Boston: Assists O/U 2.5") is None


def test_futures_title_returns_none():
    assert parse_matchup_teams("Will Atlanta Dream win the 2026 WNBA Finals?") is None
