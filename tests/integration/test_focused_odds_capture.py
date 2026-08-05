"""Integration tests for the quota-gated high-frequency capture.

The tests that matter are the ones asserting NO request was spent. A
5-minute agent that polls unconditionally is 288 requests a day, mostly
during empty afternoons and an off-season, and the failure is invisible --
the data looks fine, the quota just drains.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.pipeline.focused_odds_capture import capture_focused_odds

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)


class _ExplodingClient:
    """Any HTTP call is a test failure, so the gate is proven, not assumed."""

    def fetch_current_odds(self) -> object:  # pragma: no cover - must not run
        raise AssertionError("a request was spent when the gate should have blocked it")


def _seed_game(conn, *, start_time: datetime, status: str = "scheduled") -> int:
    home = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Home Team','HME') RETURNING id"
    ).fetchone()[0]
    away = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES ('Away Team','AWY') RETURNING id"
    ).fetchone()[0]
    return int(
        conn.execute(
            "INSERT INTO games (season, start_time, home_team_id, away_team_id, status) "
            "VALUES (2026, %s, %s, %s, %s) RETURNING id",
            (start_time, home, away, status),
        ).fetchone()[0]
    )


def _seed_fills(conn, game_id: int, count: int) -> None:
    """Hashes are unique per (game, index).

    Reusing one hash across games trips polymarket_trades_fill_key -- which
    is the constraint working, and worth leaving discoverable rather than
    papering over with ON CONFLICT in a fixture.
    """
    for index in range(count):
        conn.execute(
            "INSERT INTO polymarket_trades (transaction_hash, proxy_wallet, asset, side, "
            "condition_id, price, size, traded_at, game_id, captured_at) "
            "VALUES (%s, '0xw', '1', 'BUY', '0xc', 0.5, 10, %s, %s, %s)",
            (f"0x{game_id:032x}{index:032x}", NOW - timedelta(hours=1), game_id, NOW),
        )


def _fake_result(calls: list[int]) -> object:
    """Stand-in for a real snapshot, recording that it was reached."""
    from wnba_engine.pipeline.odds_api_ingest import OddsApiIngestResult

    calls.append(1)
    return OddsApiIngestResult(events_seen=2, rows_seen=10, rows_inserted=10)


def test_no_game_in_the_window_spends_nothing(clean_db) -> None:
    with clean_db.connection() as conn:
        _seed_game(conn, start_time=NOW + timedelta(days=4))
        conn.commit()
    result = capture_focused_odds(clean_db, _ExplodingClient(), now=NOW)
    assert result.requests_spent == 0
    assert result.games_in_window == 0
    assert "no game" in (result.skipped_reason or "")


def test_a_game_nobody_trades_is_still_watched_by_default(
    clean_db, monkeypatch
) -> None:
    """Regression test for the failure that made this agent record nothing.

    The fills gate defaulted to 25 and matched ZERO upcoming games, because
    fills only accrue against a game once the Polymarket sync has run --
    and when that sync broke, the gate silently closed. A capture agent
    whose default requires another agent to be healthy is not a gate, it is
    a second point of failure. Quota does not justify it: the plan holds
    5,000,000 requests and a full season of this costs ~0.4%.
    """
    calls: list[int] = []
    monkeypatch.setattr(
        "wnba_engine.pipeline.focused_odds_capture.snapshot_current_odds",
        lambda db, client: _fake_result(calls),
    )
    with clean_db.connection() as conn:
        _seed_game(conn, start_time=NOW + timedelta(hours=2))
        conn.commit()

    result = capture_focused_odds(clean_db, object(), now=NOW)
    assert result.requests_spent == 1
    assert result.games_watched == 1
    assert result.skipped_reason is None
    assert len(calls) == 1


def test_the_fills_gate_still_works_when_asked_for(clean_db) -> None:
    """Kept as opt-in. The gate is right for a quota-constrained plan, it
    was only wrong as a default.
    """
    with clean_db.connection() as conn:
        game_id = _seed_game(conn, start_time=NOW + timedelta(hours=2))
        _seed_fills(conn, game_id, 5)
        conn.commit()
    result = capture_focused_odds(
        clean_db, _ExplodingClient(), now=NOW, min_fills=25
    )
    assert result.requests_spent == 0
    assert result.games_in_window == 1
    assert "none with" in (result.skipped_reason or "")


def test_a_final_game_is_never_watched(clean_db) -> None:
    """A game already played has nothing left to price, and `start_time`
    alone would keep polling it for hours after the final whistle.
    """
    with clean_db.connection() as conn:
        game_id = _seed_game(conn, start_time=NOW + timedelta(hours=1), status="final")
        _seed_fills(conn, game_id, 100)
        conn.commit()
    result = capture_focused_odds(clean_db, _ExplodingClient(), now=NOW)
    assert result.requests_spent == 0


def test_a_watched_game_spends_exactly_one_request(clean_db, monkeypatch) -> None:
    """One, not one per game. the-odds-api bills /odds per market and
    region, so a per-event loop would multiply cost for identical data.
    """
    calls: list[int] = []

    def _fake_snapshot(db, client):
        del db, client
        calls.append(1)
        from wnba_engine.pipeline.odds_api_ingest import OddsApiIngestResult

        return OddsApiIngestResult(events_seen=2, rows_seen=10, rows_inserted=10)

    monkeypatch.setattr(
        "wnba_engine.pipeline.focused_odds_capture.snapshot_current_odds", _fake_snapshot
    )
    with clean_db.connection() as conn:
        first = _seed_game(conn, start_time=NOW + timedelta(hours=1))
        _seed_fills(conn, first, 30)
        second = _seed_game(conn, start_time=NOW + timedelta(hours=3))
        _seed_fills(conn, second, 40)
        conn.commit()

    result = capture_focused_odds(clean_db, object(), now=NOW)
    assert result.games_watched == 2
    assert result.requests_spent == 1
    assert len(calls) == 1
    assert result.rows_inserted == 10
