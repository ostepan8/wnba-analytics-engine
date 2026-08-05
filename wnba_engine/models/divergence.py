"""A recorded cross-venue divergence, and its later grades.

`analysis.divergence.Divergence` is what the detector produced from prices
alone; this is that plus the context needed to find it again later -- which
game, when, from which venue -- so a forward log can answer "was the price
still there" and "was it a good price" after the fact.

The grading fields are separate and nullable on purpose. What we believed
at the time is written once and never edited by what happened afterwards;
see db/migrations/0029_divergence_observations.sql.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DivergenceObservation:
    """One (moment, venue, side) where a book was below fair value."""

    game_id: int
    observed_at: datetime
    venue: str
    side: str
    book_vendor: str
    book_odds: int
    book_implied: float
    venue_fair: float
    venue_volume: float
    venue_trade_count: int
    edge: float
