"""The forward divergence log, against the real schema.

The detection rules are unit-tested in tests/unit/analysis/test_divergence.py.
What can only be tested here is the SQL: the venue price is size-weighted
across two team-naming conventions (Polymarket's outcome strings, Kalshi's
ticker suffixes) and a mistake there is silent -- an unmatched team reads
as a quiet market rather than an error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.pipeline.divergence_log import (
    grade_closings,
    log_divergences,
    recheck_prices,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 5, 18, 0, tzinfo=UTC)


def _seed_game(conn, *, start_time: datetime, status: str = "scheduled") -> int:
    home = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Indiana Fever','IND') RETURNING id"
    ).fetchone()[0]
    away = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Las Vegas Aces','LV') RETURNING id"
    ).fetchone()[0]
    return int(
        conn.execute(
            "INSERT INTO games (season, start_time, home_team_id, away_team_id, status) "
            "VALUES (2026, %s, %s, %s, %s) RETURNING id",
            (start_time, home, away, status),
        ).fetchone()[0]
    )


def _seed_quote(conn, game_id: int, vendor: str, home: int, away: int, at: datetime) -> None:
    conn.execute(
        "INSERT INTO sportsbook_game_odds (source, external_id, game_id, vendor, "
        "moneyline_home_odds, moneyline_away_odds, captured_at) "
        "VALUES ('the_odds_api', %s, %s, %s, %s, %s, %s)",
        (f"{game_id}:{vendor}:{at.isoformat()}", game_id, vendor, home, away, at),
    )


def _seed_pm(conn, game_id: int, price: float, size: float, at: datetime, n: int = 1) -> None:
    """`outcome` is the HOME team's full name, so fair_home == price."""
    for i in range(n):
        conn.execute(
            "INSERT INTO polymarket_trades (transaction_hash, proxy_wallet, asset, side, "
            "condition_id, outcome, price, size, traded_at, game_id, captured_at) "
            "VALUES (%s,'0xw','1','BUY','0xc','Indiana Fever',%s,%s,%s,%s,%s)",
            (f"0x{game_id:020x}{int(price*1000):04x}{i:08x}", price, size, at, game_id, at),
        )


def test_records_a_divergence_when_the_book_is_below_venue_fair(clean_db) -> None:
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        # -110 implies 52.4%; Polymarket says home is really 65%.
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()

    result = log_divergences(clean_db, now=NOW)
    assert result.divergences_found == 1
    assert result.rows_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT venue, side, book_vendor, book_odds, venue_fair, edge "
            "FROM divergence_observations"
        ).fetchone()
    assert row[0] == "polymarket"
    assert row[1] == "home"
    assert row[2] == "fanduel"
    assert row[3] == -110
    assert float(row[4]) == pytest.approx(0.65, abs=1e-4)
    assert float(row[5]) == pytest.approx(0.65 - 0.5238, abs=1e-3)


def test_a_game_already_under_way_is_logged_and_tagged(clean_db) -> None:
    """In-play used to be invisible: the window started at `now`, so a game
    that had tipped was excluded. That skipped 65-78% of all
    prediction-market volume, and the regime where divergence is measured
    four times as often and five times as large.
    """
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW - timedelta(minutes=40))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()

    assert log_divergences(clean_db, now=NOW).rows_inserted == 1
    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT in_play, minutes_from_tip FROM divergence_observations"
        ).fetchone()
    assert row[0] is True
    assert float(row[1]) == pytest.approx(40.0, abs=0.1)


def test_a_pre_tip_observation_is_tagged_negative_minutes(clean_db) -> None:
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()
    log_divergences(clean_db, now=NOW)
    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT in_play, minutes_from_tip FROM divergence_observations"
        ).fetchone()
    assert row[0] is False
    assert float(row[1]) == pytest.approx(-120.0, abs=0.1)


def test_a_long_finished_game_falls_outside_the_in_play_window(clean_db) -> None:
    """`status <> 'final'` is not enough on its own -- a game whose status
    never updated would otherwise be polled forever.
    """
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW - timedelta(hours=9))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(hours=9))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()
    assert log_divergences(clean_db, now=NOW).rows_inserted == 0


def test_rerunning_the_same_moment_inserts_nothing(clean_db) -> None:
    """Every 2 minutes for 6 hours is 180 runs a game; without this the
    table would fill with the same observation restated.
    """
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()

    assert log_divergences(clean_db, now=NOW).rows_inserted == 1
    again = log_divergences(clean_db, now=NOW)
    assert again.divergences_found == 1, "still detected"
    assert again.rows_inserted == 0, "but not re-recorded"


def test_an_illiquid_venue_records_nothing(clean_db) -> None:
    """The artifact that produced fake 71% edges: a market at p=0.500 on
    $10 of volume while the book has the game at 29%.
    """
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", +250, -300, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.50, 10.0, NOW - timedelta(minutes=2))
        conn.commit()
    assert log_divergences(clean_db, now=NOW).rows_inserted == 0


def test_stale_venue_trades_fall_outside_the_lookback(clean_db) -> None:
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(hours=3))
        conn.commit()
    assert log_divergences(clean_db, now=NOW).rows_inserted == 0


def test_the_venue_price_is_size_weighted_not_averaged(clean_db) -> None:
    """A $9,000 fill at 0.70 and a $1,000 fill at 0.30 is 0.66, not 0.50.
    Averaging would let one dust trade drag the fair price around.
    """
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.70, 9_000.0, NOW - timedelta(minutes=2))
        _seed_pm(conn, gid, 0.30, 1_000.0, NOW - timedelta(minutes=3))
        conn.commit()
    log_divergences(clean_db, now=NOW)
    with clean_db.connection() as conn:
        fair = conn.execute("SELECT venue_fair FROM divergence_observations").fetchone()
    assert float(fair[0]) == pytest.approx(0.66, abs=1e-3)


def test_recheck_marks_whether_the_price_survived(clean_db) -> None:
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()
    log_divergences(clean_db, now=NOW)
    with clean_db.connection() as conn:
        # the book shortens: -110 -> -140, so the price is gone
        _seed_quote(conn, gid, "fanduel", -140, +120, NOW + timedelta(minutes=2))
        conn.commit()

    result = recheck_prices(clean_db)
    assert result.written == 1
    assert result.survived == 0
    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT price_survived, recheck_odds FROM divergence_observations"
        ).fetchone()
    assert row[0] is False
    assert row[1] == -140


def test_closing_grade_computes_clv_and_outcome(clean_db) -> None:
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()
    log_divergences(clean_db, now=NOW)
    with clean_db.connection() as conn:
        _seed_quote(conn, gid, "fanduel", -150, +130, NOW + timedelta(hours=1))
        conn.execute(
            "UPDATE games SET status='final', home_score=90, away_score=80 WHERE id=%s",
            (gid,),
        )
        conn.commit()

    assert grade_closings(clean_db).written == 1
    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT closing_odds, clv, won FROM divergence_observations"
        ).fetchone()
    assert row[0] == -150
    # closing 60.0% vs taken 52.4% -> positive CLV
    assert float(row[1]) == pytest.approx(0.60 - 0.5238, abs=1e-3)
    assert row[2] is True


def test_grading_twice_does_not_restate(clean_db) -> None:
    with clean_db.connection() as conn:
        gid = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_quote(conn, gid, "fanduel", -110, -110, NOW - timedelta(minutes=1))
        _seed_pm(conn, gid, 0.65, 5_000.0, NOW - timedelta(minutes=2))
        conn.commit()
    log_divergences(clean_db, now=NOW)
    with clean_db.connection() as conn:
        _seed_quote(conn, gid, "fanduel", -150, +130, NOW + timedelta(hours=1))
        conn.execute(
            "UPDATE games SET status='final', home_score=90, away_score=80 WHERE id=%s",
            (gid,),
        )
        conn.commit()
    assert grade_closings(clean_db).written == 1
    assert grade_closings(clean_db).written == 0
