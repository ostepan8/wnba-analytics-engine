"""Event-level identity carried by every the-odds-api odds payload (current
and historical) -- separate from the per-bookmaker GameOddsRow financial
data (wnba_engine/models/odds.py), because the ingest pipeline needs to
resolve a canonical game ONCE per event (via team names + commence_time),
before persisting that event's (possibly many) per-bookmaker odds rows
against the resolved game_id. See wnba_engine/pipeline/odds_api_ingest.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from wnba_engine.models.odds import GameOddsRow


@dataclass(frozen=True, slots=True)
class OddsApiEventRef:
    external_id: str  # the-odds-api's own event id
    home_team: str
    away_team: str
    commence_time: datetime


@dataclass(frozen=True, slots=True)
class ParsedOddsEvent:
    event: OddsApiEventRef
    rows: tuple[GameOddsRow, ...]
