"""Advanced per-player-per-game stats persistence. Upserted like box scores
(not append-only): a re-run corrects the same (game, player, source) row
rather than accumulating history -- this is a computed snapshot of one
game's stats, not a time-varying signal like a price or injury status.
"""

from __future__ import annotations

from psycopg import Connection
from psycopg.types.json import Json

from wnba_engine.models.advanced_stats import PlayerAdvancedStats, TeamAdvancedStats

_UPSERT_ADVANCED_STATS = """
INSERT INTO player_advanced_stats (
    game_id, player_id, team_id, source, minutes,
    offensive_rating, defensive_rating, net_rating, pace, possessions,
    true_shooting_percentage, effective_field_goal_percentage,
    usage_percentage, assist_percentage, assist_ratio, assist_to_turnover,
    turnover_ratio, rebound_percentage, offensive_rebound_percentage,
    defensive_rebound_percentage, pie,
    free_throw_attempt_rate, team_turnover_percentage,
    opp_effective_field_goal_percentage, opp_free_throw_attempt_rate,
    opp_team_turnover_percentage, opp_offensive_rebound_percentage,
    misc_stats, usage_stats, scoring_stats
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (game_id, player_id, source) DO UPDATE SET
    team_id = EXCLUDED.team_id,
    minutes = EXCLUDED.minutes,
    offensive_rating = EXCLUDED.offensive_rating,
    defensive_rating = EXCLUDED.defensive_rating,
    net_rating = EXCLUDED.net_rating,
    pace = EXCLUDED.pace,
    possessions = EXCLUDED.possessions,
    true_shooting_percentage = EXCLUDED.true_shooting_percentage,
    effective_field_goal_percentage = EXCLUDED.effective_field_goal_percentage,
    usage_percentage = EXCLUDED.usage_percentage,
    assist_percentage = EXCLUDED.assist_percentage,
    assist_ratio = EXCLUDED.assist_ratio,
    assist_to_turnover = EXCLUDED.assist_to_turnover,
    turnover_ratio = EXCLUDED.turnover_ratio,
    rebound_percentage = EXCLUDED.rebound_percentage,
    offensive_rebound_percentage = EXCLUDED.offensive_rebound_percentage,
    defensive_rebound_percentage = EXCLUDED.defensive_rebound_percentage,
    pie = EXCLUDED.pie,
    free_throw_attempt_rate = EXCLUDED.free_throw_attempt_rate,
    team_turnover_percentage = EXCLUDED.team_turnover_percentage,
    opp_effective_field_goal_percentage = EXCLUDED.opp_effective_field_goal_percentage,
    opp_free_throw_attempt_rate = EXCLUDED.opp_free_throw_attempt_rate,
    opp_team_turnover_percentage = EXCLUDED.opp_team_turnover_percentage,
    opp_offensive_rebound_percentage = EXCLUDED.opp_offensive_rebound_percentage,
    misc_stats = EXCLUDED.misc_stats,
    usage_stats = EXCLUDED.usage_stats,
    scoring_stats = EXCLUDED.scoring_stats,
    updated_at = now()
"""


def upsert_player_advanced_stats(
    conn: Connection,
    *,
    game_id: int,
    player_id: int,
    team_id: int,
    source: str,
    stats: PlayerAdvancedStats,
) -> None:
    conn.execute(
        _UPSERT_ADVANCED_STATS,
        (
            game_id,
            player_id,
            team_id,
            source,
            stats.minutes,
            stats.offensive_rating,
            stats.defensive_rating,
            stats.net_rating,
            stats.pace,
            stats.possessions,
            stats.true_shooting_percentage,
            stats.effective_field_goal_percentage,
            stats.usage_percentage,
            stats.assist_percentage,
            stats.assist_ratio,
            stats.assist_to_turnover,
            stats.turnover_ratio,
            stats.rebound_percentage,
            stats.offensive_rebound_percentage,
            stats.defensive_rebound_percentage,
            stats.pie,
            stats.free_throw_attempt_rate,
            stats.team_turnover_percentage,
            stats.opp_effective_field_goal_percentage,
            stats.opp_free_throw_attempt_rate,
            stats.opp_team_turnover_percentage,
            stats.opp_offensive_rebound_percentage,
            Json(stats.misc_stats),
            Json(stats.usage_stats),
            Json(stats.scoring_stats),
        ),
    )


_UPSERT_TEAM_ADVANCED_STATS = """
INSERT INTO team_advanced_stats (
    game_id, team_id, source, minutes,
    offensive_rating, defensive_rating, net_rating, pace, possessions,
    true_shooting_percentage, effective_field_goal_percentage,
    usage_percentage, assist_percentage, assist_ratio, assist_to_turnover,
    turnover_ratio, rebound_percentage, offensive_rebound_percentage,
    defensive_rebound_percentage, pie,
    free_throw_attempt_rate, team_turnover_percentage,
    opp_effective_field_goal_percentage, opp_free_throw_attempt_rate,
    opp_team_turnover_percentage, opp_offensive_rebound_percentage,
    misc_stats, usage_stats, scoring_stats
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (game_id, team_id, source) DO UPDATE SET
    minutes = EXCLUDED.minutes,
    offensive_rating = EXCLUDED.offensive_rating,
    defensive_rating = EXCLUDED.defensive_rating,
    net_rating = EXCLUDED.net_rating,
    pace = EXCLUDED.pace,
    possessions = EXCLUDED.possessions,
    true_shooting_percentage = EXCLUDED.true_shooting_percentage,
    effective_field_goal_percentage = EXCLUDED.effective_field_goal_percentage,
    usage_percentage = EXCLUDED.usage_percentage,
    assist_percentage = EXCLUDED.assist_percentage,
    assist_ratio = EXCLUDED.assist_ratio,
    assist_to_turnover = EXCLUDED.assist_to_turnover,
    turnover_ratio = EXCLUDED.turnover_ratio,
    rebound_percentage = EXCLUDED.rebound_percentage,
    offensive_rebound_percentage = EXCLUDED.offensive_rebound_percentage,
    defensive_rebound_percentage = EXCLUDED.defensive_rebound_percentage,
    pie = EXCLUDED.pie,
    free_throw_attempt_rate = EXCLUDED.free_throw_attempt_rate,
    team_turnover_percentage = EXCLUDED.team_turnover_percentage,
    opp_effective_field_goal_percentage = EXCLUDED.opp_effective_field_goal_percentage,
    opp_free_throw_attempt_rate = EXCLUDED.opp_free_throw_attempt_rate,
    opp_team_turnover_percentage = EXCLUDED.opp_team_turnover_percentage,
    opp_offensive_rebound_percentage = EXCLUDED.opp_offensive_rebound_percentage,
    misc_stats = EXCLUDED.misc_stats,
    usage_stats = EXCLUDED.usage_stats,
    scoring_stats = EXCLUDED.scoring_stats,
    updated_at = now()
"""


def upsert_team_advanced_stats(
    conn: Connection,
    *,
    game_id: int,
    team_id: int,
    source: str,
    stats: TeamAdvancedStats,
) -> None:
    conn.execute(
        _UPSERT_TEAM_ADVANCED_STATS,
        (
            game_id,
            team_id,
            source,
            stats.minutes,
            stats.offensive_rating,
            stats.defensive_rating,
            stats.net_rating,
            stats.pace,
            stats.possessions,
            stats.true_shooting_percentage,
            stats.effective_field_goal_percentage,
            stats.usage_percentage,
            stats.assist_percentage,
            stats.assist_ratio,
            stats.assist_to_turnover,
            stats.turnover_ratio,
            stats.rebound_percentage,
            stats.offensive_rebound_percentage,
            stats.defensive_rebound_percentage,
            stats.pie,
            stats.free_throw_attempt_rate,
            stats.team_turnover_percentage,
            stats.opp_effective_field_goal_percentage,
            stats.opp_free_throw_attempt_rate,
            stats.opp_team_turnover_percentage,
            stats.opp_offensive_rebound_percentage,
            Json(stats.misc_stats),
            Json(stats.usage_stats),
            Json(stats.scoring_stats),
        ),
    )
