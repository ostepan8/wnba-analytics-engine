"""Assemble Polymarket and sportsbook price series per game and measure lead-lag.

The database half of `analysis/lead_lag.py`. Everything statistical lives
there; this only turns rows into two comparable series of P(home wins).

Making them comparable is the whole job, and the two venues need opposite
treatment:

- **Polymarket** needs no de-vig. The two outcomes are complementary shares
  of one dollar, so a fill's price IS a probability. That makes it a
  cleaner fair-value reference than any sportsbook.
- **Sportsbooks** quote both sides with a margin, so a raw implied
  probability sums to ~1.05 across the pair. `analysis/clv.remove_vig`
  strips it multiplicatively, the same method the CLV work already uses.

PRE-TIP ONLY. Both venues keep trading live, and in-game prices are driven
by the score rather than by information about the matchup -- pooling them
would measure "both venues watched the same game", which is true and
useless.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from psycopg import Connection

from wnba_engine.analysis import lead_lag
from wnba_engine.analysis.clv import remove_vig
from wnba_engine.db.pool import Database

logger = logging.getLogger(__name__)

#: Resampling grid. Fine enough to resolve the 16-29 minute lag
#: MODELING_FINDINGS.md describes, coarse enough that a single game's
#: burst of fills does not dominate the pooled sample.
BUCKET = timedelta(minutes=5)
#: How far from the target instant a follower observation may sit and still
#: be paired. Half the bucket, so no observation can be claimed by two
#: adjacent lags.
TOLERANCE = timedelta(minutes=2, seconds=30)
#: Lags tested, in minutes. Symmetric on purpose: a test that only looked
#: forward could not tell "Polymarket leads" from "these move together".
LAGS: tuple[int, ...] = (-60, -45, -30, -20, -15, -10, -5, 0, 5, 10, 15, 20, 30, 45, 60)


@dataclass(frozen=True, slots=True)
class BootstrapCheck:
    """Game-clustered re-test of whichever lag looked best."""

    lag_minutes: int
    correlation: float | None
    share_at_or_below_zero: float | None
    games: int


@dataclass(frozen=True, slots=True)
class LeadLagReport:
    polymarket_leads_books: lead_lag.LeadLagResult
    books_lead_polymarket: lead_lag.LeadLagResult
    games_considered: int
    bootstrap: tuple[BootstrapCheck, ...] = ()


_GAMES_SQL = """
SELECT g.id, g.start_time, h.name AS home_name, a.name AS away_name
FROM games g
JOIN teams h ON h.id = g.home_team_id
JOIN teams a ON a.id = g.away_team_id
WHERE g.status = 'final'
  AND EXISTS (SELECT 1 FROM polymarket_trades t WHERE t.game_id = g.id)
  AND EXISTS (SELECT 1 FROM sportsbook_game_odds o
              WHERE o.game_id = g.id AND o.moneyline_home_odds IS NOT NULL)
ORDER BY g.start_time
"""

_TRADES_SQL = """
SELECT traded_at, outcome, price
FROM polymarket_trades
WHERE game_id = %(game_id)s AND outcome IS NOT NULL AND traded_at < %(tip)s
ORDER BY traded_at
"""

# One row per (book, capture): de-vigging needs BOTH sides of the same
# quote, so the pair must not be split or averaged across books first.
_ODDS_SQL = """
SELECT captured_at, moneyline_home_odds, moneyline_away_odds
FROM sportsbook_game_odds
WHERE game_id = %(game_id)s
  AND moneyline_home_odds IS NOT NULL
  AND moneyline_away_odds IS NOT NULL
  AND captured_at < %(tip)s
ORDER BY captured_at
"""


def build_lead_lag_report(db: Database, *, min_points: int = 4) -> LeadLagReport:
    """Measure whether either venue's moves precede the other's.

    `min_points` drops games where one side barely traded. A game with two
    fills contributes one change, which cannot inform a lag but can add
    noise to a pooled correlation.
    """
    forward: list[tuple[list, list]] = []
    backward: list[tuple[list, list]] = []
    considered = 0

    with db.connection() as conn:
        games = conn.execute(_GAMES_SQL).fetchall()
        for game_id, tip, home_name, away_name in games:
            poly = _polymarket_series(conn, game_id, tip, home_name, away_name)
            book = _sportsbook_series(conn, game_id, tip)
            if len(poly) < min_points or len(book) < min_points:
                continue
            considered += 1
            poly_changes = lead_lag.changes(poly)
            book_changes = lead_lag.changes(book)
            forward.append((poly_changes, book_changes))
            backward.append((book_changes, poly_changes))

    logger.info("lead-lag: %d of %d games had enough data", considered, len(games))
    forward_result = lead_lag.summarise(forward, lags_minutes=LAGS, tolerance=TOLERANCE)
    backward_result = lead_lag.summarise(backward, lags_minutes=LAGS, tolerance=TOLERANCE)

    # Re-test the lags in the 15-20 minute band with the clustering the
    # pooled t ignores. These are the lags MODELING_FINDINGS.md's 16-29
    # minute claim predicts, so they are chosen a priori rather than picked
    # because they scored well -- which is the only way the number means
    # anything after fifteen lags were examined.
    checks = tuple(
        BootstrapCheck(lag, *lead_lag.bootstrap_by_game(
            forward, lag_minutes=lag, tolerance=TOLERANCE
        ))
        for lag in (15, 20)
    )
    return LeadLagReport(
        polymarket_leads_books=forward_result,
        books_lead_polymarket=backward_result,
        games_considered=considered,
        bootstrap=checks,
    )


def _polymarket_series(
    conn: Connection, game_id: int, tip, home_name: str, away_name: str
) -> Sequence[lead_lag.PricePoint]:
    rows = conn.execute(_TRADES_SQL, {"game_id": game_id, "tip": tip}).fetchall()
    points: list[lead_lag.PricePoint] = []
    for traded_at, outcome, price in rows:
        probability = lead_lag.home_probability(
            str(outcome), float(price), home_name, away_name
        )
        # None means the fill was on a prop or derivative attached to the
        # same game, not on either side of the moneyline.
        if probability is not None:
            points.append(lead_lag.PricePoint(traded_at, probability))
    return lead_lag.resample_last(points, bucket=BUCKET)


def _sportsbook_series(conn: Connection, game_id: int, tip) -> Sequence[lead_lag.PricePoint]:
    """Consensus de-vigged P(home) per capture instant.

    Averaged ACROSS BOOKS within a bucket, after de-vigging each book
    separately. Doing it in the other order would de-vig an average of
    prices that carry different margins, which is not a probability of
    anything.
    """
    rows = conn.execute(_ODDS_SQL, {"game_id": game_id, "tip": tip}).fetchall()
    points = [
        lead_lag.PricePoint(captured_at, remove_vig(int(home), int(away)).over)
        for captured_at, home, away in rows
    ]
    return lead_lag.resample_last(points, bucket=BUCKET)
