"""balldontlie injury report snapshot shapes (/wnba/v1/player_injuries).

Current-state only, same append-only-snapshot-per-fetch philosophy as
ESPN's injury_reports (see db/migrations/0005_injury_reports.sql) -- but a
genuinely thinner, free-text shape (verified live): no structured status
type code, no injury_type/side fields, a single `comment` rather than
short/long, and `return_date` is a bare "Mon D" string with no year (e.g.
"Jul 9"). See db/migrations/0016_balldontlie_injury_reports.sql for why
this doesn't share ESPN's injury_reports table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from wnba_engine.models.advanced_stats import BdlPlayerRef, BdlTeamRef


@dataclass(frozen=True, slots=True)
class BdlInjuryEntry:
    """One entry from balldontlie's live /player_injuries API."""

    player: BdlPlayerRef
    team: BdlTeamRef
    status: str
    return_date_text: str | None
    comment: str | None
    captured_at: datetime
