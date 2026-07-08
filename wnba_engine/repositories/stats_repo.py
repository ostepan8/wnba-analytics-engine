"""Box score persistence: team_game_stats and player_game_stats upserts."""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.box_scores import PlayerBoxLine, TeamBoxScore

_UPSERT_TEAM_STATS = """
INSERT INTO team_game_stats (
    game_id, team_id, source,
    field_goals_made, field_goals_attempted,
    three_pointers_made, three_pointers_attempted,
    free_throws_made, free_throws_attempted,
    rebounds, offensive_rebounds, defensive_rebounds,
    assists, steals, blocks, turnovers, fouls
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (game_id, team_id, source) DO UPDATE SET
    field_goals_made = EXCLUDED.field_goals_made,
    field_goals_attempted = EXCLUDED.field_goals_attempted,
    three_pointers_made = EXCLUDED.three_pointers_made,
    three_pointers_attempted = EXCLUDED.three_pointers_attempted,
    free_throws_made = EXCLUDED.free_throws_made,
    free_throws_attempted = EXCLUDED.free_throws_attempted,
    rebounds = EXCLUDED.rebounds,
    offensive_rebounds = EXCLUDED.offensive_rebounds,
    defensive_rebounds = EXCLUDED.defensive_rebounds,
    assists = EXCLUDED.assists,
    steals = EXCLUDED.steals,
    blocks = EXCLUDED.blocks,
    turnovers = EXCLUDED.turnovers,
    fouls = EXCLUDED.fouls,
    updated_at = now()
"""

_UPSERT_PLAYER_STATS = """
INSERT INTO player_game_stats (
    game_id, player_id, team_id, source, starter, did_not_play,
    minutes, points,
    field_goals_made, field_goals_attempted,
    three_pointers_made, three_pointers_attempted,
    free_throws_made, free_throws_attempted,
    rebounds, offensive_rebounds, defensive_rebounds,
    assists, steals, blocks, turnovers, fouls, plus_minus
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (game_id, player_id, source) DO UPDATE SET
    team_id = EXCLUDED.team_id,
    starter = EXCLUDED.starter,
    did_not_play = EXCLUDED.did_not_play,
    minutes = EXCLUDED.minutes,
    points = EXCLUDED.points,
    field_goals_made = EXCLUDED.field_goals_made,
    field_goals_attempted = EXCLUDED.field_goals_attempted,
    three_pointers_made = EXCLUDED.three_pointers_made,
    three_pointers_attempted = EXCLUDED.three_pointers_attempted,
    free_throws_made = EXCLUDED.free_throws_made,
    free_throws_attempted = EXCLUDED.free_throws_attempted,
    rebounds = EXCLUDED.rebounds,
    offensive_rebounds = EXCLUDED.offensive_rebounds,
    defensive_rebounds = EXCLUDED.defensive_rebounds,
    assists = EXCLUDED.assists,
    steals = EXCLUDED.steals,
    blocks = EXCLUDED.blocks,
    turnovers = EXCLUDED.turnovers,
    fouls = EXCLUDED.fouls,
    plus_minus = EXCLUDED.plus_minus,
    updated_at = now()
"""


def upsert_team_game_stats(
    conn: Connection, *, game_id: int, team_id: int, source: str, box: TeamBoxScore
) -> None:
    conn.execute(
        _UPSERT_TEAM_STATS,
        (
            game_id,
            team_id,
            source,
            box.field_goals.made,
            box.field_goals.attempted,
            box.three_pointers.made,
            box.three_pointers.attempted,
            box.free_throws.made,
            box.free_throws.attempted,
            box.rebounds,
            box.offensive_rebounds,
            box.defensive_rebounds,
            box.assists,
            box.steals,
            box.blocks,
            box.turnovers,
            box.fouls,
        ),
    )


def upsert_player_game_stats(
    conn: Connection,
    *,
    game_id: int,
    player_id: int,
    team_id: int,
    source: str,
    line: PlayerBoxLine,
) -> None:
    conn.execute(
        _UPSERT_PLAYER_STATS,
        (
            game_id,
            player_id,
            team_id,
            source,
            line.starter,
            line.did_not_play,
            line.minutes,
            line.points,
            line.field_goals.made if line.field_goals else None,
            line.field_goals.attempted if line.field_goals else None,
            line.three_pointers.made if line.three_pointers else None,
            line.three_pointers.attempted if line.three_pointers else None,
            line.free_throws.made if line.free_throws else None,
            line.free_throws.attempted if line.free_throws else None,
            line.rebounds,
            line.offensive_rebounds,
            line.defensive_rebounds,
            line.assists,
            line.steals,
            line.blocks,
            line.turnovers,
            line.fouls,
            line.plus_minus,
        ),
    )
