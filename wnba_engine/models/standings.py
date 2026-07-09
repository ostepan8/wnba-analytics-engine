"""Official league standings (currently balldontlie-only).

One row per team per season -- a CURRENT-STATE snapshot (standings as of
right now), not a time series of standings-over-time; see
db/migrations/0013_standings.sql. Every field here is promoted to a typed
column since standings are inherently small (~13 rows per league) and every
field is worth querying/indexing on -- unlike the per-game advanced-stats
payloads, there's no large "misc"/"usage" JSONB category to keep verbatim
here.
"""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.models.advanced_stats import BdlTeamRef


@dataclass(frozen=True, slots=True)
class StandingsRow:
    team: BdlTeamRef
    season: int
    conference: str
    wins: int
    losses: int
    win_percentage: float
    games_behind: float
    # Free-text "W-L" strings (e.g. "16-6"), not split win/loss columns --
    # verified live, same shape balldontlie uses for "minutes" elsewhere.
    home_record: str
    away_record: str
    conference_record: str
    playoff_seed: int
