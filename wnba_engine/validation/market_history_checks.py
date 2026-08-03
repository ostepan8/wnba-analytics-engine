"""Data-quality checks for polymarket_trades and kalshi_candlesticks.

These two tables arrived holding more rows than the rest of the
prediction-market data combined, and the existing bounds checks name their
tables literally, so none of them applied. A parser bug here would be
invisible until it surfaced as an inexplicable model result.

The checks are deliberately split between "the parser already enforces this"
and "only the database can see this":

- Range checks (price in [0, 1], non-negative size) duplicate parser
  validation ON PURPOSE. The parser guards the live path; these guard rows
  that arrive some other way -- a replayed capture through an older parser,
  a hand-loaded fixture, a future bulk COPY.
- Cross-row checks (a crossed book, a fill after settlement) cannot be
  expressed in a parser at all: they need the rest of the table, or another
  table entirely.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.validation import CheckResult
from wnba_engine.validation._shared import build_check_result

_TRADE_BOUNDS_SQL = """
SELECT id, condition_id, price, size
FROM polymarket_trades
WHERE price < 0 OR price > 1 OR size < 0 OR side NOT IN ('BUY', 'SELL')
"""


def check_polymarket_trade_bounds(conn: Connection) -> CheckResult:
    """A Polymarket price IS a probability, and side drives direction.

    Anything outside [0, 1] means the field is not what we think it is; a
    side other than BUY/SELL would silently invert any order-flow measure
    built on this table.
    """
    rows = conn.execute(_TRADE_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="polymarket_trade_bounds",
        description="polymarket_trades prices are probabilities and sides are BUY/SELL",
        rows=rows,
        formatter=lambda r: f"id={r[0]} condition={r[1]} price={r[2]} size={r[3]}",
    )


_CANDLE_BOUNDS_SQL = """
SELECT id, market_ticker, price_close, yes_bid_close, yes_ask_close
FROM kalshi_candlesticks
WHERE price_open   NOT BETWEEN 0 AND 1 OR price_high    NOT BETWEEN 0 AND 1
   OR price_low    NOT BETWEEN 0 AND 1 OR price_close   NOT BETWEEN 0 AND 1
   OR yes_bid_open NOT BETWEEN 0 AND 1 OR yes_bid_close NOT BETWEEN 0 AND 1
   OR yes_ask_open NOT BETWEEN 0 AND 1 OR yes_ask_close NOT BETWEEN 0 AND 1
   OR volume < 0 OR open_interest < 0
"""


def check_kalshi_candle_bounds(conn: Connection) -> CheckResult:
    """Kalshi settles at $0 or $1, so a dollar price is a probability.

    The specific failure this guards: Kalshi's legacy integer-CENT fields
    still exist alongside the dollar strings the parser reads. Reading the
    wrong one turns "16 cents" into a 1600% probability. NULL passes -- a
    bar with no trade legitimately has no price (see candle_parser).
    """
    rows = conn.execute(_CANDLE_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="kalshi_candle_bounds",
        description="kalshi_candlesticks prices stay within [0, 1] and volumes are non-negative",
        rows=rows,
        formatter=lambda r: f"id={r[0]} {r[1]} close={r[2]} bid={r[3]} ask={r[4]}",
    )


_CROSSED_BOOK_SQL = """
SELECT id, market_ticker, period_end, yes_bid_close, yes_ask_close
FROM kalshi_candlesticks
WHERE yes_bid_close IS NOT NULL
  AND yes_ask_close IS NOT NULL
  AND yes_bid_close > yes_ask_close
"""


def check_kalshi_book_is_not_crossed(conn: Connection) -> CheckResult:
    """A bid above an ask is not a market state -- it is a parse error.

    Cannot be checked in the parser: bid and ask arrive in separate blocks
    of the payload, and each is individually valid. Only comparing them
    catches the two being swapped, which is exactly the mistake a refactor
    of `_dollars(block, key)` would introduce, and which would otherwise
    show up as a free-money signal in any spread-based feature.
    """
    rows = conn.execute(_CROSSED_BOOK_SQL).fetchall()
    return build_check_result(
        name="kalshi_book_not_crossed",
        description="kalshi_candlesticks never reports a bid above its own ask",
        rows=rows,
        formatter=lambda r: f"id={r[0]} {r[1]} at {r[2]} bid={r[3]} > ask={r[4]}",
    )


_TRADE_AFTER_FINAL_SQL = """
SELECT t.id, t.condition_id, t.traded_at, g.final_observed_at
FROM polymarket_trades t
JOIN games g ON g.id = t.game_id
WHERE g.final_observed_at IS NOT NULL
  AND t.traded_at > g.final_observed_at + interval '6 hours'
"""


def check_no_trade_long_after_settlement(conn: Connection) -> CheckResult:
    """A fill on a game market long after that game was observed final.

    This is a LINKAGE check, not a market check. Trading does continue
    briefly past a final score -- positions unwind before resolution -- so
    the threshold is deliberately loose at 6 hours. What it actually
    catches is a market matched to the WRONG game: two teams meet four
    times a season, and `find_game_id_by_teams` works on a team/date
    window, so an off-by-one on the date attaches a market to the previous
    meeting. That failure is otherwise silent and would corrupt every
    per-game join downstream.
    """
    rows = conn.execute(_TRADE_AFTER_FINAL_SQL).fetchall()
    return build_check_result(
        name="no_trade_long_after_settlement",
        description="polymarket_trades are not timestamped long after their game went final",
        rows=rows,
        formatter=lambda r: f"id={r[0]} condition={r[1]} traded {r[2]} vs final {r[3]}",
    )
