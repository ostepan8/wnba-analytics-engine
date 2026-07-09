"""Play-by-play event shape (currently balldontlie-only).

No player attribution: balldontlie's plays endpoint gives a team and a
free-text description ("Rhyne Howard makes 23-foot three point jumper"),
not a structured player id. See db/migrations/0008_game_plays.sql.

Both team and description are nullable: verified live that "ejection"
plays carry neither (no team, text: null) -- an administrative event, not
a shot/rebound/etc tied to one side of the court.
"""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.models.advanced_stats import BdlGameRef, BdlTeamRef


@dataclass(frozen=True, slots=True)
class BdlPlay:
    game: BdlGameRef
    team: BdlTeamRef | None
    sequence: int
    period: int
    clock: str | None
    play_type: str
    description: str | None
    home_score: int
    away_score: int
    scoring_play: bool
    score_value: int
