"""High-frequency sportsbook capture, aimed at one open question.

MODELING_FINDINGS.md establishes that books recover 60.8% of a Polymarket
move, that the average move is ~3x too small to pay the spread, and that
the tail (>=3.8 probability points, ~7% of moves) clears it. What it CANNOT
establish is whether the book's old price was still available when the
signal fired -- our sportsbook captures are 60.1 minutes apart and the
follow-through lands inside that gap.

This exists to answer that one question and nothing else. It is not a
trading system and there is no order placement anywhere in this codebase
(see ROADMAP.md's non-goals).

QUOTA DISCIPLINE IS THE WHOLE DESIGN. A naive 5-minute cron is 288 requests
a day, most of them during an off-season or an empty afternoon, and the
resulting series is mostly identical rows. So a run does nothing at all
unless there is a game close enough to tip AND that game has enough
prediction-market activity for the test to mean anything:

  * no game inside the window        -> 0 requests
  * games in window, none with fills -> 0 requests
  * otherwise                        -> exactly ONE request

One request, because the-odds-api's /odds endpoint is billed per market and
region rather than per event: a single call returns every listed WNBA game.
Fetching per event would multiply the cost for the same data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from wnba_engine.db.pool import Database
from wnba_engine.odds_api.client import OddsApiClient
from wnba_engine.pipeline.odds_api_ingest import OddsApiIngestResult, snapshot_current_odds

logger = logging.getLogger(__name__)

#: How long before tip-off a game becomes interesting. The measured
#: follow-through window is 15-20 minutes and books move most in the hours
#: before tip, so six hours brackets the phenomenon generously without
#: polling all day.
DEFAULT_WINDOW = timedelta(hours=6)

#: Minimum Polymarket fills already recorded against a game for it to be
#: worth watching. A game nobody trades on cannot produce the >=3.8 point
#: move the test is about, so polling it burns quota to observe nothing.
DEFAULT_MIN_FILLS = 25

_TARGETS_SQL = """
SELECT g.id, g.start_time, count(t.id) AS fills
FROM games g
LEFT JOIN polymarket_trades t ON t.game_id = g.id
WHERE g.status <> 'final'
  AND g.start_time BETWEEN %(now)s AND %(until)s
GROUP BY g.id, g.start_time
HAVING count(t.id) >= %(min_fills)s
ORDER BY g.start_time
"""


@dataclass(frozen=True, slots=True)
class FocusedCaptureResult:
    games_in_window: int = 0
    games_watched: int = 0
    requests_spent: int = 0
    rows_inserted: int = 0
    skipped_reason: str | None = None


def capture_focused_odds(
    db: Database,
    client: OddsApiClient,
    *,
    window: timedelta = DEFAULT_WINDOW,
    min_fills: int = DEFAULT_MIN_FILLS,
    now: datetime | None = None,
) -> FocusedCaptureResult:
    """Snapshot sportsbook odds only when a watched game is near tip-off.

    `now` is injectable for the same reason `captured_at` is everywhere
    else in this package: a test that cannot control the clock has to
    either sleep or assert nothing.
    """
    at = now or datetime.now(UTC)
    with db.connection() as conn:
        in_window = conn.execute(
            "SELECT count(*) FROM games WHERE status <> 'final' "
            "AND start_time BETWEEN %s AND %s",
            (at, at + window),
        ).fetchone()[0]
        targets = conn.execute(
            _TARGETS_SQL,
            {"now": at, "until": at + window, "min_fills": min_fills},
        ).fetchall()

    if not targets:
        reason = (
            "no game within the window"
            if not in_window
            else f"{in_window} game(s) in window but none with >= {min_fills} fills"
        )
        logger.info("focused capture: skipped, %s (0 requests spent)", reason)
        return FocusedCaptureResult(
            games_in_window=int(in_window), skipped_reason=reason
        )

    result: OddsApiIngestResult = snapshot_current_odds(db, client)
    logger.info(
        "focused capture: %d game(s) watched, 1 request, %d row(s) inserted",
        len(targets), result.rows_inserted,
    )
    return FocusedCaptureResult(
        games_in_window=int(in_window),
        games_watched=len(targets),
        requests_spent=1,
        rows_inserted=result.rows_inserted,
    )
