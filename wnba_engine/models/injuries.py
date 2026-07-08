"""Injury report snapshot shape (currently ESPN-only).

Current-state data, not historical: see 0005_injury_reports.sql migration
comment. Every capture is a fresh, append-only snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from wnba_engine.models.box_scores import PlayerRef


@dataclass(frozen=True, slots=True)
class InjuryTeamRef:
    """A team as identified on ESPN's injuries feed.

    Deliberately NOT the shared games.TeamRef: that endpoint's team objects
    carry no abbreviation field, and reusing a shape that implies one risks
    a caller writing a blank abbreviation over a real one.
    """

    external_id: str
    name: str


@dataclass(frozen=True, slots=True)
class InjuryReportEntry:
    espn_injury_id: str
    player: PlayerRef
    team: InjuryTeamRef
    status: str
    status_type: str
    injury_type: str | None
    side: str | None
    return_date: date | None
    short_comment: str | None
    long_comment: str | None
    reported_at: datetime
    captured_at: datetime
