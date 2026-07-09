"""Season-level shot-zone efficiency splits (currently balldontlie-only).

Despite the source endpoint's name ("shot_locations"), this is NOT
per-shot x/y coordinate data -- balldontlie doesn't expose spatial shot
charts. It's field goal attempts/makes aggregated into 8 fixed court
zones per player or team per season. See db/migrations/0009_shot_zone_stats.sql.
"""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.models.advanced_stats import BdlPlayerRef, BdlTeamRef


@dataclass(frozen=True, slots=True)
class ShotZoneCounts:
    fga: int | None
    fgm: int | None


@dataclass(frozen=True, slots=True)
class ShotZoneBreakdown:
    restricted_area: ShotZoneCounts
    in_the_paint_non_ra: ShotZoneCounts
    mid_range: ShotZoneCounts
    left_corner_3: ShotZoneCounts
    right_corner_3: ShotZoneCounts
    corner_3: ShotZoneCounts
    above_the_break_3: ShotZoneCounts
    backcourt: ShotZoneCounts


@dataclass(frozen=True, slots=True)
class PlayerShotZoneStats:
    player: BdlPlayerRef
    team: BdlTeamRef | None
    season: int
    season_type: str
    zones: ShotZoneBreakdown


@dataclass(frozen=True, slots=True)
class TeamShotZoneStats:
    team: BdlTeamRef
    season: int
    season_type: str
    zones: ShotZoneBreakdown
