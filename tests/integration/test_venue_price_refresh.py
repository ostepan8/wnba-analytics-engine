"""Keeping the venue trade tables fresh enough for the divergence log.

The log reads `polymarket_trades` and `kalshi_trades` with a ten-minute
lookback, and nothing was keeping either current: both are written by
history backfills, so on 2026-08-05 the newest fill for any upcoming game
was two days old and Kalshi had none at all. The detector could never have
fired, and it would have looked like "no divergences today" rather than
like a broken feed.

These tests cover the three flags that make a recurring refresh viable.
The cost ones are not cosmetic: the first working version took 4m53s
against a two-minute cadence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.pipeline.polymarket_trade_backfill import backfill_polymarket_trades

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 5, 18, 0, tzinfo=UTC)


class _Gamma:
    """Gamma's open list: mostly season futures, a few game markets."""

    def __init__(self) -> None:
        self.closed_passes: list[bool] = []

    def fetch_wnba_events_page(self, *, closed: bool, limit: int, offset: int):
        self.closed_passes.append(closed)
        if offset > 0:
            return []
        return [
            {
                "markets": [
                    {
                        "conditionId": "0xgame",
                        "question": "Aces vs Fever",
                        "gameStartTime": (NOW + timedelta(hours=3)).isoformat(),
                    },
                    {
                        "conditionId": "0xfuture",
                        "question": "WNBA Championship 2026",
                        "gameStartTime": (NOW + timedelta(days=90)).isoformat(),
                    },
                ]
            }
        ]


class _Data:
    """Records which markets actually cost a fill fetch."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch_trades_page(self, condition_id: str, *, limit: int, offset: int):
        self.fetched.append(condition_id)
        return []


def test_open_only_skips_the_closed_pass(clean_db) -> None:
    """A settled market cannot trade again, so re-walking the archive every
    two minutes is pure cost.
    """
    gamma, data = _Gamma(), _Data()
    backfill_polymarket_trades(
        clean_db, gamma, data, resume=False, open_only=True, captured_at=NOW
    )
    assert gamma.closed_passes and all(c is False for c in gamma.closed_passes)


def test_the_full_backfill_still_walks_both_passes(clean_db) -> None:
    """The history path must not regress -- the closed pass carries almost
    everything for a backfill.
    """
    gamma, data = _Gamma(), _Data()
    backfill_polymarket_trades(clean_db, gamma, data, resume=False, captured_at=NOW)
    assert True in gamma.closed_passes
    assert False in gamma.closed_passes


def test_close_within_drops_markets_that_are_not_about_to_settle(clean_db) -> None:
    gamma, data = _Gamma(), _Data()
    result = backfill_polymarket_trades(
        clean_db,
        gamma,
        data,
        resume=False,
        open_only=True,
        close_within=timedelta(hours=48),
        captured_at=NOW,
    )
    assert result.markets_seen == 1, "the championship future is 90 days out"
    assert "0xfuture" not in data.fetched


def test_require_game_match_resolves_before_paying_for_fills(clean_db) -> None:
    """The expensive part of this backfill is the paginated fill walk, so
    an unmatched market must be dropped BEFORE it, not after. A live run
    fetched 104 open markets to keep 7 before this was reordered.
    """
    gamma, data = _Gamma(), _Data()
    result = backfill_polymarket_trades(
        clean_db,
        gamma,
        data,
        resume=False,
        open_only=True,
        require_game_match=True,
        captured_at=NOW,
    )
    # No games are seeded, so nothing resolves and nothing should be fetched.
    assert data.fetched == []
    assert result.markets_fetched == 0
    assert result.markets_skipped == result.markets_seen


def test_without_the_flag_unmatched_markets_are_still_stored(clean_db) -> None:
    """Storing a fill we cannot yet attribute to a game is correct for the
    history path: the relink pass repairs game ids later.
    """
    gamma, data = _Gamma(), _Data()
    backfill_polymarket_trades(
        clean_db, gamma, data, resume=False, open_only=True, captured_at=NOW
    )
    assert "0xgame" in data.fetched
