"""Persistence for recoverable prediction-market history.

Both tables are append-only and both return ACTUAL rowcount, so re-running a
backfill correctly reports 0 rather than re-reporting the same work as new.

The idempotency key deliberately excludes `captured_at` -- see
db/migrations/0025_prediction_market_history.sql. That is the opposite of
every other append-only table here, and the reason is that these rows are
immutable facts rather than repeated observations: including capture time
would let a second backfill run duplicate the first one wholesale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import Connection

from wnba_engine.models.market_history import KalshiCandle, PolymarketTrade

_INSERT_TRADE = """
INSERT INTO polymarket_trades (
    transaction_hash, proxy_wallet, asset, side, condition_id,
    outcome, outcome_index, price, size, traded_at,
    title, slug, event_slug, game_id, captured_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT ON CONSTRAINT polymarket_trades_fill_key DO NOTHING
"""

_INSERT_CANDLE = """
INSERT INTO kalshi_candlesticks (
    series_ticker, market_ticker, period_minutes, period_end,
    price_open, price_high, price_low, price_close, price_mean, price_previous,
    yes_bid_open, yes_bid_high, yes_bid_low, yes_bid_close,
    yes_ask_open, yes_ask_high, yes_ask_low, yes_ask_close,
    volume, open_interest, game_id, captured_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT ON CONSTRAINT kalshi_candlesticks_bar_key DO NOTHING
"""


def insert_trades(
    conn: Connection,
    trades: Sequence[PolymarketTrade],
    *,
    game_id_by_condition: Mapping[str, int] | None = None,
) -> int:
    """Append fills; returns how many were ACTUALLY written.

    `game_id_by_condition` is keyed on condition id rather than per trade
    because every fill in one market resolves to the same game -- doing the
    lookup per trade would issue hundreds of identical queries for a single
    market and, worse, could disagree with itself if the matcher were ever
    made non-deterministic.
    """
    by_condition = game_id_by_condition or {}
    if not trades:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(
            _INSERT_TRADE,
            [
                (
                    t.transaction_hash,
                    t.proxy_wallet,
                    t.asset,
                    t.side,
                    t.condition_id,
                    t.outcome,
                    t.outcome_index,
                    t.price,
                    t.size,
                    t.traded_at,
                    t.title,
                    t.slug,
                    t.event_slug,
                    by_condition.get(t.condition_id),
                    t.captured_at,
                )
                for t in trades
            ],
        )
        return max(cursor.rowcount, 0)


def insert_candles(
    conn: Connection,
    candles: Sequence[KalshiCandle],
    *,
    game_id_by_market: Mapping[str, int] | None = None,
) -> int:
    """Append OHLC bars; returns how many were ACTUALLY written."""
    by_market = game_id_by_market or {}
    if not candles:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(
            _INSERT_CANDLE,
            [
                (
                    c.series_ticker,
                    c.market_ticker,
                    c.period_minutes,
                    c.period_end,
                    c.price_open,
                    c.price_high,
                    c.price_low,
                    c.price_close,
                    c.price_mean,
                    c.price_previous,
                    c.yes_bid_open,
                    c.yes_bid_high,
                    c.yes_bid_low,
                    c.yes_bid_close,
                    c.yes_ask_open,
                    c.yes_ask_high,
                    c.yes_ask_low,
                    c.yes_ask_close,
                    c.volume,
                    c.open_interest,
                    by_market.get(c.market_ticker),
                    c.captured_at,
                )
                for c in candles
            ],
        )
        return max(cursor.rowcount, 0)


def known_condition_ids(conn: Connection) -> frozenset[str]:
    """Condition ids that already have at least one stored fill.

    Lets a resumed backfill skip markets it has finished, which matters
    because the alternative -- re-walking every page to discover that
    ON CONFLICT rejects all of it -- costs the same number of HTTP requests
    as the original run. Correctness never depends on this: the UNIQUE
    constraint is what guarantees no duplication.

    Deliberately NOT used to skip markets that are still open. A market that
    traded yesterday will trade again today, so `--since` in the pipeline
    controls that, not this set.
    """
    rows = conn.execute("SELECT DISTINCT condition_id FROM polymarket_trades").fetchall()
    return frozenset(str(row[0]) for row in rows)


def latest_candle_end(conn: Connection, market_ticker: str, period_minutes: int) -> object:
    """Newest bar end already stored for one market at one resolution."""
    row = conn.execute(
        "SELECT max(period_end) FROM kalshi_candlesticks "
        "WHERE market_ticker = %s AND period_minutes = %s",
        (market_ticker, period_minutes),
    ).fetchone()
    return row[0] if row else None
