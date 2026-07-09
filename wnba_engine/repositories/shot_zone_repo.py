"""Season-level shot-zone stats persistence. Upserted like advanced stats:
a re-run corrects the same (player/team, season, season_type, source) row
rather than accumulating history -- this is a computed season aggregate,
not a time-varying signal.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.shot_zones import (
    PlayerShotZoneStats,
    ShotZoneBreakdown,
    TeamShotZoneStats,
)

_UPSERT_PLAYER_SHOT_ZONES = """
INSERT INTO player_shot_zone_stats (
    player_id, team_id, season, season_type, source,
    restricted_area_fga, restricted_area_fgm,
    in_the_paint_non_ra_fga, in_the_paint_non_ra_fgm,
    mid_range_fga, mid_range_fgm,
    left_corner_3_fga, left_corner_3_fgm,
    right_corner_3_fga, right_corner_3_fgm,
    corner_3_fga, corner_3_fgm,
    above_the_break_3_fga, above_the_break_3_fgm,
    backcourt_fga, backcourt_fgm
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (player_id, season, season_type, source) DO UPDATE SET
    team_id = EXCLUDED.team_id,
    restricted_area_fga = EXCLUDED.restricted_area_fga,
    restricted_area_fgm = EXCLUDED.restricted_area_fgm,
    in_the_paint_non_ra_fga = EXCLUDED.in_the_paint_non_ra_fga,
    in_the_paint_non_ra_fgm = EXCLUDED.in_the_paint_non_ra_fgm,
    mid_range_fga = EXCLUDED.mid_range_fga,
    mid_range_fgm = EXCLUDED.mid_range_fgm,
    left_corner_3_fga = EXCLUDED.left_corner_3_fga,
    left_corner_3_fgm = EXCLUDED.left_corner_3_fgm,
    right_corner_3_fga = EXCLUDED.right_corner_3_fga,
    right_corner_3_fgm = EXCLUDED.right_corner_3_fgm,
    corner_3_fga = EXCLUDED.corner_3_fga,
    corner_3_fgm = EXCLUDED.corner_3_fgm,
    above_the_break_3_fga = EXCLUDED.above_the_break_3_fga,
    above_the_break_3_fgm = EXCLUDED.above_the_break_3_fgm,
    backcourt_fga = EXCLUDED.backcourt_fga,
    backcourt_fgm = EXCLUDED.backcourt_fgm,
    updated_at = now()
"""

_UPSERT_TEAM_SHOT_ZONES = """
INSERT INTO team_shot_zone_stats (
    team_id, season, season_type, source,
    restricted_area_fga, restricted_area_fgm,
    in_the_paint_non_ra_fga, in_the_paint_non_ra_fgm,
    mid_range_fga, mid_range_fgm,
    left_corner_3_fga, left_corner_3_fgm,
    right_corner_3_fga, right_corner_3_fgm,
    corner_3_fga, corner_3_fgm,
    above_the_break_3_fga, above_the_break_3_fgm,
    backcourt_fga, backcourt_fgm
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (team_id, season, season_type, source) DO UPDATE SET
    restricted_area_fga = EXCLUDED.restricted_area_fga,
    restricted_area_fgm = EXCLUDED.restricted_area_fgm,
    in_the_paint_non_ra_fga = EXCLUDED.in_the_paint_non_ra_fga,
    in_the_paint_non_ra_fgm = EXCLUDED.in_the_paint_non_ra_fgm,
    mid_range_fga = EXCLUDED.mid_range_fga,
    mid_range_fgm = EXCLUDED.mid_range_fgm,
    left_corner_3_fga = EXCLUDED.left_corner_3_fga,
    left_corner_3_fgm = EXCLUDED.left_corner_3_fgm,
    right_corner_3_fga = EXCLUDED.right_corner_3_fga,
    right_corner_3_fgm = EXCLUDED.right_corner_3_fgm,
    corner_3_fga = EXCLUDED.corner_3_fga,
    corner_3_fgm = EXCLUDED.corner_3_fgm,
    above_the_break_3_fga = EXCLUDED.above_the_break_3_fga,
    above_the_break_3_fgm = EXCLUDED.above_the_break_3_fgm,
    backcourt_fga = EXCLUDED.backcourt_fga,
    backcourt_fgm = EXCLUDED.backcourt_fgm,
    updated_at = now()
"""


def _zone_values(zones: ShotZoneBreakdown) -> tuple[object, ...]:
    return (
        zones.restricted_area.fga,
        zones.restricted_area.fgm,
        zones.in_the_paint_non_ra.fga,
        zones.in_the_paint_non_ra.fgm,
        zones.mid_range.fga,
        zones.mid_range.fgm,
        zones.left_corner_3.fga,
        zones.left_corner_3.fgm,
        zones.right_corner_3.fga,
        zones.right_corner_3.fgm,
        zones.corner_3.fga,
        zones.corner_3.fgm,
        zones.above_the_break_3.fga,
        zones.above_the_break_3.fgm,
        zones.backcourt.fga,
        zones.backcourt.fgm,
    )


def upsert_player_shot_zone_stats(
    conn: Connection,
    *,
    player_id: int,
    team_id: int | None,
    source: str,
    stats: PlayerShotZoneStats,
) -> None:
    conn.execute(
        _UPSERT_PLAYER_SHOT_ZONES,
        (player_id, team_id, stats.season, stats.season_type, source, *_zone_values(stats.zones)),
    )


def upsert_team_shot_zone_stats(
    conn: Connection,
    *,
    team_id: int,
    source: str,
    stats: TeamShotZoneStats,
) -> None:
    conn.execute(
        _UPSERT_TEAM_SHOT_ZONES,
        (team_id, stats.season, stats.season_type, source, *_zone_values(stats.zones)),
    )
