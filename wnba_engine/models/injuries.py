"""Injury report snapshot shapes (ESPN live API + Wayback archive).

Both are current-state-at-capture-time data: every capture is a fresh,
append-only snapshot. See 0005_injury_reports.sql for why the live source
has no historical version, and the Wayback backfill pipeline for how the
Internet Archive fills that gap for 2022-2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from wnba_engine.models.box_scores import PlayerRef


@dataclass(frozen=True, slots=True)
class InjuryTeamRef:
    """A team as identified on ESPN's live injuries feed.

    Deliberately NOT the shared games.TeamRef: that endpoint's team objects
    carry no abbreviation field, and reusing a shape that implies one risks
    a caller writing a blank abbreviation over a real one.
    """

    external_id: str
    name: str


@dataclass(frozen=True, slots=True)
class InjuryReportEntry:
    """One entry from ESPN's live /injuries API."""

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


@dataclass(frozen=True, slots=True)
class WaybackInjuryEntry:
    """One entry from an archived ESPN injuries page snapshot.

    Team is identified by abbreviation (extracted from a team logo URL) --
    this older page format carries no team id, unlike the live API. There
    are no structured body-part/side/return-date fields either, just a
    free-text description; the "date" field has no year, so reported_at is
    inferred from the snapshot's own capture date (see
    wayback_injuries_parser._infer_reported_at).
    """

    player: PlayerRef
    team_abbreviation: str
    status: str
    status_type: str
    description: str | None
    reported_at: datetime
    captured_at: datetime
