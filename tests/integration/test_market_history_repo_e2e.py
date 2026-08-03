"""Integration tests for polymarket_trades / kalshi_candlesticks.

These exist for one reason: db/migrations/0025 deliberately breaks the house
`UNIQUE(<external identity>, captured_at)` convention, and a broken
idempotency key does not fail -- it silently doubles a table. The tests that
matter here are the ones that re-insert with a DIFFERENT captured_at and
assert nothing was written.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.models.market_history import KalshiCandle, PolymarketTrade
from wnba_engine.repositories import market_history_repo

pytestmark = pytest.mark.integration

FIRST_RUN = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)
SECOND_RUN = FIRST_RUN + timedelta(days=1)


def _trade(**overrides: object) -> PolymarketTrade:
    base = PolymarketTrade(
        transaction_hash="0x323a4af09271a8ebd3e838b3a4501f8fa8a9b54a858dab6e3969e5192f0be3e8",
        proxy_wallet="0x6dab26eb9853b8bc7b9d91f622617fbd19a7e5c0",
        asset="686143065106683052719414783448050022773205980249637716526841924854",
        side="BUY",
        condition_id="0x4f0cc49d5b8e2ba8e7b33f200dc2a6150bf3511daa8558c39578d28c89772cd2",
        outcome="Seattle Storm",
        outcome_index=0,
        price=0.001,
        size=1000.0,
        traded_at=datetime(2026, 6, 2, 3, 17, 1, tzinfo=UTC),
        title="Seattle Storm vs. Dallas Wings",
        slug="wnba-sea-dal-2026-06-01",
        event_slug="wnba-sea-dal-2026-06-01",
        captured_at=FIRST_RUN,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _candle(**overrides: object) -> KalshiCandle:
    base = KalshiCandle(
        series_ticker="KXWNBAGAME",
        market_ticker="KXWNBAGAME-26AUG02TORGS-TOR",
        title="Toronto vs Golden State women's Pro Basketball game: Toronto wins?",
        period_minutes=60,
        period_end=datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
        price_open=0.16, price_high=0.16, price_low=0.16, price_close=0.16,
        price_mean=0.16, price_previous=0.16,
        yes_bid_open=0.15, yes_bid_high=0.15, yes_bid_low=0.15, yes_bid_close=0.15,
        yes_ask_open=0.16, yes_ask_high=0.16, yes_ask_low=0.16, yes_ask_close=0.16,
        volume=135.88, open_interest=2802.57,
        captured_at=FIRST_RUN,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _stored_game_id(conn):
    return conn.execute("SELECT game_id FROM kalshi_candlesticks LIMIT 1").fetchone()[0]


def _seed_game(conn) -> int:
    home = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('H Team','HME') RETURNING id"
    ).fetchone()[0]
    away = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('A Team','AWY') RETURNING id"
    ).fetchone()[0]
    return int(
        conn.execute(
            "INSERT INTO games (season, start_time, home_team_id, away_team_id, status, "
            "home_score, away_score) VALUES (2026, %s, %s, %s, 'final', 90, 80) RETURNING id",
            (FIRST_RUN, home, away),
        ).fetchone()[0]
    )


def test_a_second_backfill_run_inserts_nothing(clean_db) -> None:
    """THE test for migration 0025's deviation.

    Every other append-only table here keys on (identity, captured_at)
    because it stores repeated observations of mutable state. A fill is an
    immutable fact, so captured_at is deliberately NOT in the key -- if it
    were, this second run (a day later, same trade) would duplicate the
    whole table, which is precisely what the constraint exists to prevent.
    """
    with clean_db.connection() as conn:
        assert market_history_repo.insert_trades(conn, [_trade()]) == 1
        conn.commit()
        assert market_history_repo.insert_trades(conn, [_trade(captured_at=SECOND_RUN)]) == 0
        conn.commit()
        total = conn.execute("SELECT count(*) FROM polymarket_trades").fetchone()[0]
    assert total == 1


def test_a_candle_refetched_later_inserts_nothing(clean_db) -> None:
    """Re-fetching an already-complete bar must report 0, not "updated".

    The candle insert is a CONFLICT-UPDATE (0026) so an improved matcher
    can repair a NULL game_id. A bare DO UPDATE would count every
    conflicting row as written and a re-run would claim tens of thousands
    of inserts it never made -- so the update carries a WHERE restricting
    it to rows that actually need repair.
    """
    with clean_db.connection() as conn:
        game_id = _seed_game(conn)
        mapping = {_candle().market_ticker: game_id}
        assert market_history_repo.insert_candles(
            conn, [_candle()], game_id_by_market=mapping
        ) == 1
        conn.commit()
        # Nothing left to fill: game_id and title are both already set, so
        # the WHERE on the conflict-update excludes this row entirely.
        assert market_history_repo.insert_candles(
            conn, [_candle(captured_at=SECOND_RUN)], game_id_by_market=mapping
        ) == 0
        conn.commit()
        total = conn.execute("SELECT count(*) FROM kalshi_candlesticks").fetchone()[0]
    assert total == 1


def test_a_refetch_repairs_a_null_game_id(clean_db) -> None:
    """The whole reason 0026 exists.

    The first sweep resolved only KXWNBAGAME, leaving 118,495 spread and
    total bars with a NULL game_id, and ON CONFLICT DO NOTHING meant fixing
    the resolver could not repair them. Now a re-run fills the gap -- and
    never overwrites a game_id already set.
    """
    with clean_db.connection() as conn:
        game_id = _seed_game(conn)
        market_history_repo.insert_candles(conn, [_candle()])
        conn.commit()
        assert _stored_game_id(conn) is None

        repaired = market_history_repo.insert_candles(
            conn, [_candle()], game_id_by_market={_candle().market_ticker: game_id}
        )
        conn.commit()
        assert repaired == 1
        assert _stored_game_id(conn) == game_id

        # Idempotent: a third run has nothing left to fill.
        assert market_history_repo.insert_candles(
            conn, [_candle()], game_id_by_market={_candle().market_ticker: game_id}
        ) == 0


def test_both_sides_of_one_transaction_are_stored(clean_db) -> None:
    """Polymarket records both sides of a trade separately on-chain, and a
    batched transaction can carry several fills. Keying on the hash ALONE
    would drop all but one of them -- which is why the constraint also
    names the wallet, the token and the direction.
    """
    with clean_db.connection() as conn:
        buyer = _trade(side="BUY", proxy_wallet="0xaaa")
        seller = _trade(side="SELL", proxy_wallet="0xbbb")
        assert market_history_repo.insert_trades(conn, [buyer, seller]) == 2
        conn.commit()
        total = conn.execute("SELECT count(*) FROM polymarket_trades").fetchone()[0]
    assert total == 2


def test_the_same_instant_at_two_resolutions_is_not_a_conflict(clean_db) -> None:
    """A 1-minute and a 60-minute bar legitimately share an end instant."""
    with clean_db.connection() as conn:
        assert market_history_repo.insert_candles(
            conn, [_candle(period_minutes=60), _candle(period_minutes=1)]
        ) == 2
        conn.commit()


def test_known_condition_ids_reports_what_is_stored(clean_db) -> None:
    """Drives the backfill's resume path. Correctness never depends on it --
    the UNIQUE constraint does -- but a wrong answer here either re-walks
    every market or skips one entirely.
    """
    with clean_db.connection() as conn:
        assert market_history_repo.known_condition_ids(conn) == frozenset()
        market_history_repo.insert_trades(conn, [_trade()])
        conn.commit()
        assert market_history_repo.known_condition_ids(conn) == frozenset({_trade().condition_id})


def test_inserting_nothing_is_not_an_error(clean_db) -> None:
    """A market that never traded yields an empty batch, which is the
    ordinary case across a multi-year sweep, not a failure.
    """
    with clean_db.connection() as conn:
        assert market_history_repo.insert_trades(conn, []) == 0
        assert market_history_repo.insert_candles(conn, []) == 0
