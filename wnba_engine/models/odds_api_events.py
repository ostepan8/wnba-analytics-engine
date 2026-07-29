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

from wnba_engine.models.odds import GameOddsRow, PlayerPropOddsRow


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


@dataclass(frozen=True, slots=True)
class OddsApiPropRow:
    """One parsed player-prop line, still carrying the player's NAME rather
    than an id.

    the-odds-api exposes no player identifier anywhere in a prop payload --
    the player exists only as the free-text `description` on each outcome
    (verified live). So unlike balldontlie's props, which carry that
    provider's own numeric player id and resolve through the crosswalk,
    these can only be resolved by name against players.full_name. Keeping
    the raw name on this model (rather than resolving inside the parser)
    preserves the repo's parser/pipeline split: parsers stay pure and
    database-free, and the name→id resolution happens in the pipeline
    where a connection exists.
    """

    player_name: str
    row: PlayerPropOddsRow


@dataclass(frozen=True, slots=True)
class ParsedPropEvent:
    event: OddsApiEventRef
    props: tuple[OddsApiPropRow, ...]
