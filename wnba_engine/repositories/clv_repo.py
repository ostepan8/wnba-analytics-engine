"""Pairing each prop quote with the price the same market closed at.

Read-only. The pairing is per (game, player, prop_type, vendor): CLV
compares one book's price against THAT BOOK'S close, not against a
cross-book consensus, because a bet is placed at one book and settles
against the number that book actually finished on.

"Closing" here means the last capture strictly before tip-off. That is an
approximation of the true close -- captures arrive on a 2-hourly cadence,
so the real final price can be up to that much later. It biases toward
understating movement (a late move after our last capture is invisible),
which is the safe direction for a metric whose failure mode is claiming
edge that isn't there.

In-play captures are excluded: a price set after tip-off already knows
part of the answer, and grading against it would flatter any pick.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

_OPEN_CLOSE_PAIRS_SQL = """
WITH pregame AS (
    SELECT pp.game_id, pp.player_id, pp.prop_type, pp.vendor,
           pp.line_value, pp.over_odds, pp.under_odds, pp.captured_at,
           ROW_NUMBER() OVER (
               PARTITION BY pp.game_id, pp.player_id, pp.prop_type, pp.vendor
               ORDER BY pp.captured_at ASC) AS first_rn,
           ROW_NUMBER() OVER (
               PARTITION BY pp.game_id, pp.player_id, pp.prop_type, pp.vendor
               ORDER BY pp.captured_at DESC) AS last_rn
    FROM sportsbook_player_prop_odds pp
    JOIN games g ON g.id = pp.game_id
    WHERE pp.market_type = 'over_under'
      -- Both sides required: betrivers publishes Over-only through
      -- the-odds-api (see DATA_INVENTORY.md), and a one-sided quote
      -- cannot be de-vigged.
      AND pp.over_odds IS NOT NULL
      AND pp.under_odds IS NOT NULL
      AND pp.captured_at < g.start_time
      AND (%(prop_types)s::text[] IS NULL OR pp.prop_type = ANY(%(prop_types)s::text[]))
      AND (%(seasons)s::int[] IS NULL OR g.season = ANY(%(seasons)s::int[]))
)
SELECT o.game_id, o.player_id, o.prop_type, o.vendor,
       o.line_value  AS open_line,  o.over_odds AS open_over,  o.under_odds AS open_under,
       o.captured_at AS open_at,
       c.line_value  AS close_line, c.over_odds AS close_over, c.under_odds AS close_under,
       c.captured_at AS close_at
FROM pregame o
JOIN pregame c
  ON  c.game_id = o.game_id AND c.player_id = o.player_id
  AND c.prop_type = o.prop_type AND c.vendor = o.vendor
  AND c.last_rn = 1
WHERE o.first_rn = 1
  -- A single capture is its own close; there is no movement to measure.
  AND c.captured_at > o.captured_at
"""


@dataclass(frozen=True, slots=True)
class OpenClosePair:
    game_id: int
    player_id: int
    prop_type: str
    vendor: str
    open_line: float
    open_over: int
    open_under: int
    open_at: datetime
    close_line: float
    close_over: int
    close_under: int
    close_at: datetime


def load_open_close_pairs(
    conn: Connection,
    *,
    prop_types: Sequence[str] | None = None,
    seasons: Sequence[int] | None = None,
) -> tuple[OpenClosePair, ...]:
    """Every prop's first and last pre-game quote, per book."""
    rows = conn.execute(
        _OPEN_CLOSE_PAIRS_SQL,
        {
            "prop_types": list(prop_types) if prop_types else None,
            "seasons": list(seasons) if seasons else None,
        },
    ).fetchall()
    return tuple(
        OpenClosePair(
            game_id=int(r[0]),
            player_id=int(r[1]),
            prop_type=str(r[2]),
            vendor=str(r[3]),
            open_line=float(r[4]),
            open_over=int(r[5]),
            open_under=int(r[6]),
            open_at=r[7],
            close_line=float(r[8]),
            close_over=int(r[9]),
            close_under=int(r[10]),
            close_at=r[11],
        )
        for r in rows
    )
