"""Persistence for the hand-researched season_awards ground-truth table.

See db/migrations/0017_season_awards.sql for the schema and
wnba_engine/pipeline/season_awards_seed.py for the researched data and why
this is seeded by a one-off script rather than a live pipeline.
"""

from __future__ import annotations

from psycopg import Connection

_INSERT_AWARD = """
INSERT INTO season_awards (
    season, award, team_selection, player_id, raw_name, team_id, source
) VALUES (
    %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (season, award, team_selection, raw_name) DO NOTHING
RETURNING id
"""


def insert_award_winner(
    conn: Connection,
    *,
    season: int,
    award: str,
    raw_name: str,
    source: str,
    team_selection: str = "na",
    player_id: int | None = None,
    team_id: int | None = None,
) -> bool:
    """Insert one award-winner row.

    Returns True if a new row was inserted, False if it already existed --
    the dedup key is (season, award, team_selection, raw_name), see
    0017_season_awards.sql. Idempotent: re-running the seed script is
    always safe.
    """
    row = conn.execute(
        _INSERT_AWARD,
        (season, award, team_selection, player_id, raw_name, team_id, source),
    ).fetchone()
    return row is not None
