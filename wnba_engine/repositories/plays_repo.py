"""Play-by-play persistence. Bulk-inserted per game with ON CONFLICT DO
NOTHING: a finished game's plays are a fixed historical record that never
needs correcting, unlike advanced stats which upserts to absorb
provider-side revisions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import Connection

from wnba_engine.models.plays import BdlPlay

_INSERT_PLAY = """
INSERT INTO game_plays (
    game_id, team_id, source, sequence, period, clock, play_type,
    description, home_score, away_score, scoring_play, score_value
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (game_id, sequence, source) DO NOTHING
"""


def insert_plays(
    conn: Connection,
    *,
    game_id: int,
    source: str,
    plays: Sequence[BdlPlay],
    team_id_by_external_id: Mapping[str, int],
) -> int:
    """Bulk-insert one game's plays; returns the number of rows attempted
    (not necessarily inserted -- ON CONFLICT DO NOTHING silently skips
    rows a prior run already wrote, and executemany's affected-row count
    isn't reliably available across drivers, so this is a request-size
    metric, not a precise insert count).
    """
    with conn.cursor() as cursor:
        cursor.executemany(
            _INSERT_PLAY,
            [
                (
                    game_id,
                    team_id_by_external_id.get(play.team.external_id) if play.team else None,
                    source,
                    play.sequence,
                    play.period,
                    play.clock,
                    play.play_type,
                    play.description,
                    play.home_score,
                    play.away_score,
                    play.scoring_play,
                    play.score_value,
                )
                for play in plays
            ],
        )
    return len(plays)
