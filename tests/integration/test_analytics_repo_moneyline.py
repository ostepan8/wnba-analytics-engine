"""The moneyline filter behind /games/{id}/markets, against the real schema.

This exists because the obvious query is wrong in a way that looks right.
market_price_snapshots holds every market a venue lists for a game -- one
August 2026 game carried 118 distinct outcomes, including player props, quarter
and half totals, spreads, margins and "Tie". Selecting by game_id alone and
charting the result produces a plausible-looking line that means nothing.

The subtler trap, and the reason this is an integration test rather than a unit
one: Kalshi's per-quarter winner markets carry the SAME `outcome` value as the
full-game market and a title differing only in a trailing clause. Filtering on
the team label alone silently mixes five markets into one series, which reads as
a price oscillating between 0.005 and 0.995 several times a minute. Only the
ticker prefix separates them, and only a query against the real column can prove
it does.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.repositories import analytics_repo

pytestmark = pytest.mark.integration

CAPTURED_AT = datetime(2026, 8, 17, 1, 6, 52, tzinfo=UTC)


def _seed_game(conn) -> int:
    home = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Phoenix Mercury','PHX') RETURNING id"
    ).fetchone()[0]
    away = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Portland Fire','PDX') RETURNING id"
    ).fetchone()[0]
    return int(
        conn.execute(
            "INSERT INTO games (season, start_time, home_team_id, away_team_id, status) "
            "VALUES (2026, %s, %s, %s, 'scheduled') RETURNING id",
            (CAPTURED_AT, home, away),
        ).fetchone()[0]
    )


def _snapshot(conn, game_id, *, provider, external_id, outcome, probability, title="t"):
    conn.execute(
        "INSERT INTO market_price_snapshots "
        "(provider, market_external_id, game_id, title, outcome, implied_probability, "
        " status, captured_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)",
        (provider, external_id, game_id, title, outcome, probability, CAPTURED_AT),
    )


@pytest.fixture
def game_with_markets(clean_db):
    with clean_db.connection() as conn:
        game_id = _seed_game(conn)

        # The full-game moneyline, both sides. This is the only thing that should
        # come back.
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAGAME-26AUG16PDXPHX-PHX",
                  outcome="Phoenix", probability="0.655")
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAGAME-26AUG16PDXPHX-PDX",
                  outcome="Portland", probability="0.345")

        # Quarter winners: identical outcome labels, different series.
        for quarter in (1, 2, 3, 4):
            _snapshot(conn, game_id, provider="kalshi",
                      external_id=f"KXWNBA{quarter}QWINNER-26AUG16PDXPHX-PHX",
                      outcome="Phoenix", probability="0.005")

        # Derivative markets whose outcome is not a bare team name.
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAGAMEH1-26AUG16PDXPHX-PHX",
                  outcome="Phoenix wins 1st half", probability="0.60")
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAGAMESPREAD-26AUG16PDXPHX",
                  outcome="Phoenix wins by over 4.5 points", probability="0.40")
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAGAMETOTAL-26AUG16PDXPHX",
                  outcome="Over 163.5 points scored", probability="0.52")
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAGAMETIE-26AUG16PDXPHX",
                  outcome="Tie", probability="0.01")

        # A player prop, the largest category by row count in real data.
        _snapshot(conn, game_id, provider="kalshi",
                  external_id="KXWNBAPTS-26AUG16PDXPHX-COPPER",
                  outcome="Kahleah Copper: 20+", probability="0.44")

        # Polymarket's combined game market: NULL outcome, side unrecoverable.
        _snapshot(conn, game_id, provider="polymarket",
                  external_id="3298438", outcome=None, probability="0.325")

        conn.commit()
    return clean_db, game_id


def fetch(db, game_id):
    with db.connection() as conn:
        return analytics_repo.fetch_game_market_prices(conn, game_id, limit=500)


def test_only_the_full_game_moneyline_is_returned(game_with_markets) -> None:
    db, game_id = game_with_markets
    rows = fetch(db, game_id)

    assert len(rows) == 2
    assert {row["outcome"] for row in rows} == {"Phoenix", "Portland"}
    assert all(row["market_external_id"].startswith("KXWNBAGAME-") for row in rows)


def test_quarter_winner_markets_are_excluded(game_with_markets) -> None:
    """They share the outcome label with the moneyline; only the ticker differs.
    Including them is what made the chart oscillate between 0.005 and 0.995."""
    db, game_id = game_with_markets
    probabilities = {float(row["implied_probability"]) for row in fetch(db, game_id)}
    assert 0.005 not in probabilities


def test_props_totals_spreads_and_ties_are_excluded(game_with_markets) -> None:
    db, game_id = game_with_markets
    outcomes = {row["outcome"] for row in fetch(db, game_id)}
    for excluded in (
        "Kahleah Copper: 20+",
        "Over 163.5 points scored",
        "Phoenix wins by over 4.5 points",
        "Phoenix wins 1st half",
        "Tie",
    ):
        assert excluded not in outcomes


def test_each_row_is_resolved_to_a_side(game_with_markets) -> None:
    """Returned by the query, not derived by the caller: normalising two venues
    onto one home-win-probability axis must not require a client to
    re-implement team matching."""
    db, game_id = game_with_markets
    sides = {row["outcome"]: row["side"] for row in fetch(db, game_id)}
    assert sides == {"Phoenix": "home", "Portland": "away"}


def test_polymarkets_unresolvable_game_market_is_excluded(game_with_markets) -> None:
    """One price, NULL outcome, no way to tell which side it is from this table.
    Excluded rather than guessed at -- a 50/50 guess would silently invert the
    whole series."""
    db, game_id = game_with_markets
    assert all(row["provider"] != "polymarket" for row in fetch(db, game_id))
