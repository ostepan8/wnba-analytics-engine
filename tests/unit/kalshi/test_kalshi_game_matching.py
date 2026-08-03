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


def test_the_2026_title_format_with_the_sport_clause_still_resolves() -> None:
    """Kalshi rewrote KXWNBAGAME titles between 2026-07-13 and 2026-07-27.

        before: "Indiana vs Los Angeles winner?"
        after:  "Las Vegas vs Chicago women's Pro Basketball game: Chicago wins?"

    The old regex anchored on a literal " winner?" suffix, so every market
    after the change parsed as None and silently stopped resolving to a
    game: 4,712 KXWNBAGAME snapshot rows went from a 31-34% match rate to
    0.0%, measured against the live database on 2026-08-03. Nothing failed
    -- game_id just became NULL, which reads exactly like a market we chose
    not to map.

    Both shapes must keep working: the database holds rows in the old
    format that a re-ingest would otherwise orphan in the opposite
    direction.
    """
    assert parse_matchup(
        "KXWNBAGAME-26AUG01LVCHI-CHI",
        "Las Vegas vs Chicago women's Pro Basketball game: Chicago wins?",
    ) == (date(2026, 8, 1), "Las Vegas", "Chicago")
    assert parse_matchup(
        "KXWNBAGAME-26AUG02CONNDAL-CONN",
        "Connecticut vs Dallas women's Pro Basketball game: Connecticut wins?",
    ) == (date(2026, 8, 2), "Connecticut", "Dallas")


def test_the_pre_2026_07_27_title_format_still_resolves() -> None:
    assert parse_matchup("KXWNBAGAME-26JUL09INDPHX", "Indiana vs Phoenix winner?") == (
        date(2026, 7, 9),
        "Indiana",
        "Phoenix",
    )
