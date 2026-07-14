"""the-odds-api /v4/sports/basketball_wnba/scores -- a second, independent
final-score source used ONLY as a cross-check against games.home_score/
away_score (see wnba_engine/validation/consistency_checks.py). Never
written back into games.home_score/away_score -- that precedence decision
(db/migrations/0001_canonical_entities.sql) is deliberately out of scope
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class OddsApiGameScore:
    """One completed game's final score as reported by the-odds-api, as of
    `captured_at` (the row's own `last_update` -- a genuine source-side "as
    of" timestamp, same convention as GameOddsRow.updated_at)."""

    external_id: str  # the-odds-api's own event id
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    # Carried alongside captured_at (the score's own last_update) because
    # the two can be many hours apart (observed live: last_update ~10h
    # after commence_time) -- game resolution must anchor on commence_time,
    # not captured_at, or a reasonable match window will miss the game
    # entirely.
    commence_time: datetime
    captured_at: datetime
