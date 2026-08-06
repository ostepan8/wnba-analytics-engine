"""Persistence for the forward divergence log.

Append-only for observations, and returns ACTUAL rowcount so re-running the
detector over a moment already recorded correctly reports 0 rather than
re-reporting the same work as new.

Grading is a separate write path, and it only ever fills NULLs. A graded
row is never re-graded, which keeps the log honest under re-runs: the
closing price is whatever was true the first time it was computed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from psycopg import Connection

from wnba_engine.models.divergence import DivergenceObservation

_INSERT = """
INSERT INTO divergence_observations (
    game_id, observed_at, venue, side, book_vendor, book_odds, book_implied,
    venue_fair, venue_volume, venue_trade_count, edge, in_play, minutes_from_tip
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT ON CONSTRAINT divergence_observations_moment_key DO NOTHING
"""

_UNGRADED_FOR_RECHECK = """
SELECT id, game_id, observed_at, side, book_odds
FROM divergence_observations
WHERE price_survived IS NULL
ORDER BY observed_at
"""

_UNGRADED_FOR_CLOSE = """
SELECT d.id, d.game_id, d.side, d.book_implied
FROM divergence_observations d
JOIN games g ON g.id = d.game_id
WHERE d.graded_at IS NULL AND g.status = 'final'
ORDER BY d.observed_at
"""

# Only ever writes into NULLs, so a second grading run is a no-op rather
# than a restatement.
_WRITE_RECHECK = """
UPDATE divergence_observations
SET recheck_at = %s, recheck_odds = %s, price_survived = %s
WHERE id = %s AND price_survived IS NULL
"""

_WRITE_GRADE = """
UPDATE divergence_observations
SET closing_odds = %s, closing_implied = %s, clv = %s, won = %s, graded_at = now()
WHERE id = %s AND graded_at IS NULL
"""


def record_divergences(
    conn: Connection, observations: Sequence[DivergenceObservation]
) -> int:
    """Insert observations, returning how many were genuinely new."""
    if not observations:
        return 0
    inserted = 0
    for o in observations:
        cur = conn.execute(
            _INSERT,
            (
                o.game_id,
                o.observed_at,
                o.venue,
                o.side,
                o.book_vendor,
                o.book_odds,
                o.book_implied,
                o.venue_fair,
                o.venue_volume,
                o.venue_trade_count,
                o.edge,
                o.in_play,
                o.minutes_from_tip,
            ),
        )
        inserted += cur.rowcount
    return inserted


def pending_recheck(conn: Connection) -> list[tuple]:
    return conn.execute(_UNGRADED_FOR_RECHECK).fetchall()


def pending_close_grade(conn: Connection) -> list[tuple]:
    return conn.execute(_UNGRADED_FOR_CLOSE).fetchall()


def write_recheck(
    conn: Connection,
    observation_id: int,
    *,
    recheck_at: datetime,
    recheck_odds: int,
    survived: bool,
) -> int:
    cur = conn.execute(
        _WRITE_RECHECK, (recheck_at, recheck_odds, survived, observation_id)
    )
    return cur.rowcount


def write_close_grade(
    conn: Connection,
    observation_id: int,
    *,
    closing_odds: int,
    closing_implied: float,
    clv: float,
    won: bool,
) -> int:
    cur = conn.execute(
        _WRITE_GRADE,
        (closing_odds, closing_implied, clv, won, observation_id),
    )
    return cur.rowcount
