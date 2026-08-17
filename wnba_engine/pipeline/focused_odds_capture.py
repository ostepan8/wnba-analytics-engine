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

ONE GATE, AND IT IS THE FREE ONE. A run does nothing unless a game is
close enough to tip:

  * no game inside the window -> 0 requests
  * otherwise                 -> exactly ONE request

That gate costs nothing to be right about -- an off-season or an empty
afternoon has no game in the window, so it spends nothing -- and it does
not depend on any other part of the system being healthy.

There used to be a second gate requiring recorded Polymarket activity, and
it is why this file has no data to show for the weeks it ran. See
DEFAULT_MIN_FILLS. It survives as an opt-in parameter, not a default.

Resolution matters more than frugality here. The follow-through being
measured is 15-20 minutes wide, so the capture interval has to be a small
fraction of that; the plist runs every two minutes. Dense polling is also
cheaper than it looks in storage terms, because `captured_at` is each
book's own `last_update` and the unique constraint is ON CONFLICT DO
NOTHING -- a book that has not moved inserts nothing. The series that
results is a record of actual price CHANGES with real timestamps, which is
exactly what the lead-lag question needs and what hourly capture destroys.

One request, because the-odds-api's /odds endpoint is billed per market and
region rather than per event: a single call returns every listed WNBA game.
Fetching per event would multiply the cost for the same data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from wnba_engine.db.pool import Database
from wnba_engine.odds_api.client import MONEYLINE_ONLY_MARKETS, OddsApiClient
from wnba_engine.pipeline.odds_api_ingest import OddsApiIngestResult, snapshot_current_odds

logger = logging.getLogger(__name__)

#: How long before tip-off a game becomes interesting. The measured
#: follow-through window is 15-20 minutes and books move most in the hours
#: before tip, so six hours brackets the phenomenon generously without
#: polling all day.
DEFAULT_WINDOW = timedelta(hours=6)

#: How long AFTER tip-off a game stays worth capturing.
#:
#: Added 2026-08-06. Until then this agent only watched games that had not
#: started, which meant the sportsbook side of the in-play market was never
#: deliberately captured -- the 3,888 in-play rows we had arrived by
#: accident, from an hourly snapshot that happened not to filter by tip.
#: That is the wrong two-thirds to be blind to: 65-78% of prediction-market
#: volume trades after tip-off, and the divergence there is measured four
#: times more often and five times larger.
#:
#: A WNBA game runs about two hours plus stoppages; three hours covers
#: overtime and a late start without polling an already-finished game for
#: long, since `status <> 'final'` closes it out anyway.
DEFAULT_IN_PLAY_WINDOW = timedelta(hours=3)

#: Minimum Polymarket fills already recorded against a game for it to be
#: worth watching. **Defaults to 0 -- off.**
#:
#: This defaulted to 25 and cost the experiment its data. Fills only accrue
#: against a game once the Polymarket sync has run, so when that sync broke
#: (a stale worktree path, exit 127) the gate silently closed and every run
#: for weeks reported "0 requests spent" while looking perfectly healthy.
#: A capture agent whose default requires a *different* agent to be healthy
#: is not a gate, it is a second point of failure -- and one that fails
#: closed and quietly.
#:
#: The quota argument that justified it does not hold: the plan carries
#: 5,000,000 requests (424 used as of 2026-08-05), and capturing every
#: WNBA game for a whole season at two-minute resolution costs ~0.4% of it.
#: Kept as an opt-in parameter because it is the right gate on a small
#: plan, and wrong only as a default.
DEFAULT_MIN_FILLS = 0

_TARGETS_SQL = """
SELECT g.id, g.start_time, count(t.id) AS fills
FROM games g
LEFT JOIN polymarket_trades t ON t.game_id = g.id
WHERE g.status <> 'final'
  AND g.start_time BETWEEN %(since)s AND %(until)s
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
    in_play_window: timedelta = DEFAULT_IN_PLAY_WINDOW,
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
        since = at - in_play_window
        in_window = conn.execute(
            "SELECT count(*) FROM games WHERE status <> 'final' "
            "AND start_time BETWEEN %s AND %s",
            (since, at + window),
        ).fetchone()[0]
        targets = conn.execute(
            _TARGETS_SQL,
            {"since": since, "until": at + window, "min_fills": min_fills},
        ).fetchall()

    if not targets:
        reason = (
            "no game within the window"
            if not in_window
            else f"{in_window} game(s) in window but none with >= {min_fills} fills"
        )
        # DEBUG, not INFO: at a two-minute interval this fires ~720 times a
        # day and is a skip almost every time. Logged at INFO it is 1,400
        # lines a day of "nothing happened", which is how the real entries
        # get lost. Liveness belongs to `launchctl print`, not to a log
        # nobody can skim.
        logger.debug("focused capture: skipped, %s (0 requests spent)", reason)
        return FocusedCaptureResult(
            games_in_window=int(in_window), skipped_reason=reason
        )

    # Moneyline only. This capture exists to feed the divergence log, which
    # reads the two moneyline columns and nothing else, and the-odds-api prices
    # a request at [markets] x [regions] -- so asking for spreads and totals
    # here tripled the cost of the highest-frequency job in the system for data
    # it never used. The 2-hourly routine snapshot still takes all three.
    result: OddsApiIngestResult = snapshot_current_odds(
        db, client, markets=MONEYLINE_ONLY_MARKETS
    )
    logger.info(
        "focused capture: %d game(s) watched, 1 request (1 credit), %d row(s) inserted",
        len(targets), result.rows_inserted,
    )
    return FocusedCaptureResult(
        games_in_window=int(in_window),
        games_watched=len(targets),
        requests_spent=1,
        rows_inserted=result.rows_inserted,
    )
