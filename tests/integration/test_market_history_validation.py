"""Integration tests for the polymarket_trades / kalshi_candlesticks checks.

Same shape as test_data_validation.py: each check gets a deliberately-bad
row inserted with raw SQL, plus a clean case proving it does not cry wolf.
Raw SQL on purpose -- the parsers reject most of these, and the point is
that the DATABASE still catches a row that arrived some other way (a
replayed capture through an older parser, a bulk load, a fixture).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.validation import market_history_checks as checks

pytestmark = pytest.mark.integration

TRADED_AT = datetime(2026, 6, 2, 3, 17, 1, tzinfo=UTC)


def _insert_trade(conn, **overrides) -> None:
    row = {
        "transaction_hash": "0xdeadbeef",
        "proxy_wallet": "0xwallet",
        "asset": "12345",
        "side": "BUY",
        "condition_id": "0xcondition",
        "price": 0.55,
        "size": 100,
        "traded_at": TRADED_AT,
        "captured_at": TRADED_AT,
        "game_id": None,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    conn.execute(
        f"INSERT INTO polymarket_trades ({columns}) VALUES ({placeholders})",  # noqa: S608
        tuple(row.values()),
    )


def _insert_candle(conn, **overrides) -> None:
    row = {
        "series_ticker": "KXWNBAGAME",
        "market_ticker": "KXWNBAGAME-26AUG02TORGS-TOR",
        "period_minutes": 60,
        "period_end": datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
        "price_close": 0.16,
        "yes_bid_close": 0.15,
        "yes_ask_close": 0.16,
        "volume": 10,
        "open_interest": 100,
        "captured_at": TRADED_AT,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    conn.execute(
        f"INSERT INTO kalshi_candlesticks ({columns}) VALUES ({placeholders})",  # noqa: S608
        tuple(row.values()),
    )


def _seed_final_game(conn, *, final_observed_at: datetime) -> int:
    home = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Home Team','HME') RETURNING id"
    ).fetchone()[0]
    away = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Away Team','AWY') RETURNING id"
    ).fetchone()[0]
    return int(
        conn.execute(
            "INSERT INTO games (season, start_time, home_team_id, away_team_id, status, "
            "home_score, away_score, final_observed_at) "
            "VALUES (2026, %s, %s, %s, 'final', 90, 80, %s) RETURNING id",
            (TRADED_AT - timedelta(hours=3), home, away, final_observed_at),
        ).fetchone()[0]
    )


def test_a_price_above_one_is_caught(clean_db) -> None:
    with clean_db.connection() as conn:
        _insert_trade(conn, price=1.5)
        result = checks.check_polymarket_trade_bounds(conn)
    assert result.violation_count == 1


def test_an_unknown_side_is_caught(clean_db) -> None:
    """The parser rejects it, but a replayed capture through an older
    parser would not have. side drives direction on every flow measure.
    """
    with clean_db.connection() as conn:
        _insert_trade(conn, side="MINT")
        result = checks.check_polymarket_trade_bounds(conn)
    assert result.violation_count == 1


def test_ordinary_trades_pass(clean_db) -> None:
    with clean_db.connection() as conn:
        _insert_trade(conn, price=0.0, transaction_hash="0xa")
        _insert_trade(conn, price=1.0, transaction_hash="0xb")
        _insert_trade(conn, side="SELL", transaction_hash="0xc")
        result = checks.check_polymarket_trade_bounds(conn)
    assert result.violation_count == 0


def test_a_cent_denominated_candle_price_is_caught(clean_db) -> None:
    """The concrete regression: Kalshi's legacy integer-CENT fields still
    exist beside the dollar strings the parser reads. Reading the wrong
    one stores 16 cents as a 1600% probability.
    """
    with clean_db.connection() as conn:
        _insert_candle(conn, price_close=16)
        result = checks.check_kalshi_candle_bounds(conn)
    assert result.violation_count == 1


def test_a_candle_with_no_trade_is_not_a_violation(clean_db) -> None:
    """Kalshi omits the price block on a bar where nothing traded. NULL is
    the honest answer there and must not be mistaken for out-of-range.
    """
    with clean_db.connection() as conn:
        _insert_candle(conn, price_close=None, volume=0)
        result = checks.check_kalshi_candle_bounds(conn)
    assert result.violation_count == 0


def test_a_crossed_book_is_caught(clean_db) -> None:
    """Bid above ask is not a market state. Unreachable from the parser --
    the two arrive in separate payload blocks, each individually valid --
    so only comparing them catches a swap.
    """
    with clean_db.connection() as conn:
        _insert_candle(conn, yes_bid_close=0.60, yes_ask_close=0.40)
        result = checks.check_kalshi_book_is_not_crossed(conn)
    assert result.violation_count == 1


def test_a_normal_and_a_locked_book_both_pass(clean_db) -> None:
    """bid == ask is a locked market, which is legal and does happen."""
    with clean_db.connection() as conn:
        _insert_candle(conn, yes_bid_close=0.15, yes_ask_close=0.16)
        _insert_candle(conn, period_minutes=1, yes_bid_close=0.20, yes_ask_close=0.20)
        result = checks.check_kalshi_book_is_not_crossed(conn)
    assert result.violation_count == 0


def test_a_fill_long_after_the_final_is_caught(clean_db) -> None:
    """Really a mis-linkage check: two teams meet four times a season, so
    an off-by-one in the team/date window attaches a market to the wrong
    meeting, and this is the cheapest way to see that.
    """
    with clean_db.connection() as conn:
        game_id = _seed_final_game(conn, final_observed_at=TRADED_AT - timedelta(days=3))
        _insert_trade(conn, game_id=game_id)
        result = checks.check_no_trade_long_after_settlement(conn)
    assert result.violation_count == 1


def test_a_fill_shortly_after_the_final_is_allowed(clean_db) -> None:
    """Positions unwind before resolution, so trading past the final score
    is normal. The threshold is loose on purpose -- 6 hours -- because the
    target is a mis-linked game, not a late unwind.
    """
    with clean_db.connection() as conn:
        game_id = _seed_final_game(conn, final_observed_at=TRADED_AT - timedelta(hours=1))
        _insert_trade(conn, game_id=game_id)
        result = checks.check_no_trade_long_after_settlement(conn)
    assert result.violation_count == 0


def test_an_unlinked_trade_cannot_trip_the_settlement_check(clean_db) -> None:
    """Futures and props stay unlinked by design; a NULL game_id must not
    be read as a violation of a game it was never attached to.
    """
    with clean_db.connection() as conn:
        _insert_trade(conn, game_id=None, traded_at=datetime(2030, 1, 1, tzinfo=UTC))
        result = checks.check_no_trade_long_after_settlement(conn)
    assert result.violation_count == 0
