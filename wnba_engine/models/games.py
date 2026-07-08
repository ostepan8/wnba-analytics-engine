"""Canonical game/team shapes produced by scoreboard-style feeds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class GameStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"
    OTHER = "other"


class SeasonType(StrEnum):
    """ESPN's season.type: 1=preseason, 2=regular-season, 3=post-season.

    Preseason and postseason games have the same shape as a regular-season
    game in every other respect, so without this a preseason win looks
    identical to a real one -- this was a real bug (inflated 2026 Minnesota
    standings, 18-6 instead of 15-6) before this field existed.
    """

    PRESEASON = "preseason"
    REGULAR_SEASON = "regular-season"
    POSTSEASON = "post-season"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class TeamRef:
    """A team as identified by one provider (external id + display info)."""

    external_id: str
    name: str
    abbreviation: str


@dataclass(frozen=True, slots=True)
class ScoreboardGame:
    """One game from a provider scoreboard, normalized."""

    external_id: str
    start_time: datetime
    season: int
    season_type: SeasonType
    status: GameStatus
    home_team: TeamRef
    away_team: TeamRef
    home_score: int | None
    away_score: int | None

    @property
    def is_final(self) -> bool:
        return self.status is GameStatus.FINAL
