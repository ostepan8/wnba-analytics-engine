"""Persistence for stats.wnba.com plays and shot locations."""

from __future__ import annotations

from collections.abc import Sequence

from psycopg import Connection

_INSERT_PLAY = """
INSERT INTO game_plays (
    game_id, team_id, source, sequence, period, clock, play_type, description,
    home_score, away_score, scoring_play, score_value,
    player1_id, player2_id, player3_id, event_type, event_action_type
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (game_id, sequence, source) DO UPDATE SET
    player1_id = COALESCE(game_plays.player1_id, EXCLUDED.player1_id),
    player2_id = COALESCE(game_plays.player2_id, EXCLUDED.player2_id),
    player3_id = COALESCE(game_plays.player3_id, EXCLUDED.player3_id)
WHERE game_plays.player1_id IS NULL
   OR (EXCLUDED.player2_id IS NOT NULL AND game_plays.player2_id IS NULL)
   OR (EXCLUDED.player3_id IS NOT NULL AND game_plays.player3_id IS NULL)
"""

_INSERT_SHOT = """
INSERT INTO shot_locations (
    game_id, player_id, team_id, source, game_event_id, period, seconds_remaining,
    action_type, shot_type, shot_zone_basic, shot_zone_area, shot_zone_range,
    shot_distance, loc_x, loc_y, made
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT ON CONSTRAINT shot_locations_event_key DO NOTHING
"""


def insert_plays(conn: Connection, rows: Sequence[tuple]) -> int:
    """Append plays; returns rows ACTUALLY written.

    CONFLICT-UPDATE onto NULL player columns only, for the same reason
    kalshi_candlesticks does it (0026): a re-run after the name matcher
    improves must be able to fill an attribution it could not resolve the
    first time, and DO NOTHING cannot. The WHERE keeps the rowcount honest
    -- a re-run over fully-resolved rows reports 0.
    """
    if not rows:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(_INSERT_PLAY, rows)
        return max(cursor.rowcount, 0)


def insert_shots(conn: Connection, rows: Sequence[tuple]) -> int:
    """Append shot locations; returns rows ACTUALLY written."""
    if not rows:
        return 0
    with conn.cursor() as cursor:
        cursor.executemany(_INSERT_SHOT, rows)
        return max(cursor.rowcount, 0)


def games_with_source(conn: Connection, source: str) -> frozenset[int]:
    """Canonical game ids that already have plays from `source`."""
    rows = conn.execute(
        "SELECT DISTINCT game_id FROM game_plays WHERE source = %s", (source,)
    ).fetchall()
    return frozenset(int(r[0]) for r in rows)


def games_with_shots(conn: Connection, source: str) -> frozenset[int]:
    rows = conn.execute(
        "SELECT DISTINCT game_id FROM shot_locations WHERE source = %s", (source,)
    ).fetchall()
    return frozenset(int(r[0]) for r in rows)
