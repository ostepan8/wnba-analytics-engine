"""balldontlie game shape, used only to resolve balldontlie's own game ids
to our canonical games via team+date matching (entity_repo.find_game_id_by_teams).

Deliberately not the shared games.ScoreboardGame: this is a crosswalk-
resolution helper, not a source of truth for scores/status -- ESPN already
owns that (see 0001_canonical_entities.sql precedence note).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BdlGameMatchup:
    external_id: str
    home_team_full_name: str
    away_team_full_name: str
    start_time: datetime
