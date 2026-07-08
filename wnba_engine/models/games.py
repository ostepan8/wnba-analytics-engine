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
    status: GameStatus
    home_team: TeamRef
    away_team: TeamRef
    home_score: int | None
    away_score: int | None

    @property
    def is_final(self) -> bool:
        return self.status is GameStatus.FINAL
