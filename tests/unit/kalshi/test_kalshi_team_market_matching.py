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


def test_the_2026_sport_clause_does_not_leak_into_the_team_name() -> None:
    """The same 2026-07-27 title rewrite, one module over -- and this one
    fails WORSE than game_matching's did.

    `_TWO_TEAM_RE` matched the new shape rather than rejecting it, but the
    non-greedy second group swallowed the inserted clause:

        "Atlanta vs Dallas women's Pro Basketball game: Over 166.5 points?"
        -> team_b = "Dallas women's Pro Basketball game"

    A returned-but-wrong team name means the downstream substring lookup
    finds nothing, so the failure still surfaces as NULL game_id -- 13,330
    KXWNBATOTAL rows since 2026-07-27, against 633/1146 matching the week
    before. Asserting on the exact team name, not merely on "not None", is
    the point of this test.
    """
    assert parse_two_team_market(
        "KXWNBATOTAL-26AUG03ATLDAL",
        "Atlanta vs Dallas women's Pro Basketball game: Over 166.5 points?",
    ) == (date(2026, 8, 3), "Atlanta", "Dallas")


def test_the_older_two_team_shapes_are_unaffected() -> None:
    assert parse_two_team_market(
        "KXWNBATOTAL-26JUL08GSTOR", "Golden State vs Toronto: 1st Quarter Total?"
    ) == (date(2026, 7, 8), "Golden State", "Toronto")
    assert parse_two_team_market(
        "KXWNBAOT-26JUL08GSTOR", "Golden State vs Toronto on Jul 8, 2026: Overtime?"
    ) == (date(2026, 7, 8), "Golden State", "Toronto")


def test_the_2026_spread_title_inserts_the_game_and_still_resolves() -> None:
    """The THIRD matcher broken by Kalshi's 2026-07-27 title rewrite.

    game_matching and the two-team pattern were fixed when the KXWNBAGAME
    and KXWNBATOTAL breakage surfaced. The single-team spread shape was
    missed, because the clause it gained is different:

        before: "Indiana wins by over 7.5 points?"
        after:  "Las Vegas wins the game by over 19.5 points?"

    Consequence: every one of 68,963 KXWNBASPREAD candlestick bars was
    stored with a NULL game_id, and re-running the backfill could not fix
    it because the title never parsed at all.
    """
    assert parse_single_team_market(
        "KXWNBASPREAD-26JUL28PDXLV", "Las Vegas wins the game by over 19.5 points?"
    ) == (date(2026, 7, 28), "Las Vegas")


def test_a_market_ticker_resolves_as_well_as_its_event_ticker() -> None:
    """Callers hold different halves of the identity.

    kalshi_ingest has the event ticker; relink-market-games only has the
    MARKET ticker, which carries a trailing outcome segment
    ('...-GS26'). The date regex is end-anchored, so the market form
    matched nothing and the repair silently resolved zero markets.
    """
    expected = (date(2026, 8, 2), "Golden State")
    title = "Golden State wins the game by over 25.5 points?"
    assert parse_single_team_market("KXWNBASPREAD-26AUG02TORGS", title) == expected
    assert parse_single_team_market("KXWNBASPREAD-26AUG02TORGS-GS26", title) == expected


def test_the_pre_rewrite_spread_shapes_still_resolve() -> None:
    assert parse_single_team_market(
        "KXWNBASPREAD-26JUL09INDPHX", "Indiana wins by over 7.5 points?"
    ) == (date(2026, 7, 9), "Indiana")
    assert parse_single_team_market(
        "KXWNBA1HSPREAD-26JUL09INDATL", "Will Atlanta win the 1H by over 1.5 points?"
    ) == (date(2026, 7, 9), "Atlanta")
