"""Plausibility bounds -- values that are structurally impossible
regardless of source (makes exceeding attempts, sub-splits not summing to
their total, probabilities outside [0, 1]).
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.validation import CheckResult
from wnba_engine.validation._shared import build_check_result

_TEAM_STAT_BOUNDS_SQL = """
SELECT game_id, team_id, 'fgm>fga' AS violation FROM team_game_stats
WHERE field_goals_made > field_goals_attempted
UNION ALL
SELECT game_id, team_id, '3pm>3pa' FROM team_game_stats
WHERE three_pointers_made > three_pointers_attempted
UNION ALL
SELECT game_id, team_id, 'ftm>fta' FROM team_game_stats
WHERE free_throws_made > free_throws_attempted
UNION ALL
SELECT game_id, team_id, 'oreb+dreb<>reb' FROM team_game_stats
WHERE offensive_rebounds + defensive_rebounds <> rebounds
"""


def check_team_stat_bounds(conn: Connection) -> CheckResult:
    """team_game_stats has no shooting split where makes exceed attempts,
    and offensive+defensive rebounds always sum to the total."""
    rows = conn.execute(_TEAM_STAT_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="team_stat_bounds",
        description="team_game_stats has no makes>attempts or oreb+dreb<>rebounds",
        rows=rows,
        formatter=lambda r: f"game={r[0]} team={r[1]}: {r[2]}",
    )


_PLAYER_STAT_BOUNDS_SQL = """
SELECT game_id, player_id, 'fgm>fga' AS violation FROM player_game_stats
WHERE field_goals_made > field_goals_attempted
UNION ALL
SELECT game_id, player_id, '3pm>3pa' FROM player_game_stats
WHERE three_pointers_made > three_pointers_attempted
UNION ALL
SELECT game_id, player_id, 'ftm>fta' FROM player_game_stats
WHERE free_throws_made > free_throws_attempted
UNION ALL
SELECT game_id, player_id, 'oreb+dreb<>reb' FROM player_game_stats
WHERE offensive_rebounds + defensive_rebounds <> rebounds
"""


def check_player_stat_bounds(conn: Connection) -> CheckResult:
    """Same bounds as check_team_stat_bounds, at the player-row level.
    NULL stat columns (did_not_play players) never satisfy these
    comparisons, so DNP rows are naturally excluded without a filter."""
    rows = conn.execute(_PLAYER_STAT_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="player_stat_bounds",
        description="player_game_stats has no makes>attempts or oreb+dreb<>rebounds",
        rows=rows,
        formatter=lambda r: f"game={r[0]} player={r[1]}: {r[2]}",
    )


_MARKET_PRICE_BOUNDS_SQL = """
SELECT id, provider, market_external_id
FROM market_price_snapshots
WHERE (implied_probability IS NOT NULL AND (implied_probability < 0 OR implied_probability > 1))
   OR (yes_bid IS NOT NULL AND (yes_bid < 0 OR yes_bid > 1))
   OR (yes_ask IS NOT NULL AND (yes_ask < 0 OR yes_ask > 1))
"""


def check_market_price_bounds(conn: Connection) -> CheckResult:
    """Implied probability and bid/ask are normalized to [0, 1] at parse
    time (see models/markets.py) -- anything outside that range slipped
    past normalization."""
    rows = conn.execute(_MARKET_PRICE_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="market_price_bounds",
        description="market_price_snapshots probabilities/bid/ask stay within [0, 1]",
        rows=rows,
        formatter=lambda r: f"id={r[0]} {r[1]}/{r[2]}",
    )


_PLAYER_SHOT_ZONE_BOUNDS_SQL = """
SELECT id, player_id FROM player_shot_zone_stats
WHERE restricted_area_fgm > restricted_area_fga
   OR in_the_paint_non_ra_fgm > in_the_paint_non_ra_fga
   OR mid_range_fgm > mid_range_fga
   OR left_corner_3_fgm > left_corner_3_fga
   OR right_corner_3_fgm > right_corner_3_fga
   OR corner_3_fgm > corner_3_fga
   OR above_the_break_3_fgm > above_the_break_3_fga
   OR backcourt_fgm > backcourt_fga
"""


def check_player_shot_zone_bounds(conn: Connection) -> CheckResult:
    """No shot zone can have more makes than attempts."""
    rows = conn.execute(_PLAYER_SHOT_ZONE_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="player_shot_zone_bounds",
        description="player_shot_zone_stats has no zone with fgm > fga",
        rows=rows,
        formatter=lambda r: f"id={r[0]} player={r[1]}",
    )


_TEAM_SHOT_ZONE_BOUNDS_SQL = """
SELECT id, team_id FROM team_shot_zone_stats
WHERE restricted_area_fgm > restricted_area_fga
   OR in_the_paint_non_ra_fgm > in_the_paint_non_ra_fga
   OR mid_range_fgm > mid_range_fga
   OR left_corner_3_fgm > left_corner_3_fga
   OR right_corner_3_fgm > right_corner_3_fga
   OR corner_3_fgm > corner_3_fga
   OR above_the_break_3_fgm > above_the_break_3_fga
   OR backcourt_fgm > backcourt_fga
"""


def check_team_shot_zone_bounds(conn: Connection) -> CheckResult:
    """No shot zone can have more makes than attempts."""
    rows = conn.execute(_TEAM_SHOT_ZONE_BOUNDS_SQL).fetchall()
    return build_check_result(
        name="team_shot_zone_bounds",
        description="team_shot_zone_stats has no zone with fgm > fga",
        rows=rows,
        formatter=lambda r: f"id={r[0]} team={r[1]}",
    )
