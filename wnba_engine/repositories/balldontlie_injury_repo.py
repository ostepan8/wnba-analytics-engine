"""balldontlie injury report snapshot persistence. Append-only -- never
updated. See db/migrations/0016_balldontlie_injury_reports.sql for why
this is a separate table from ESPN's injury_reports (see injury_repo.py)
rather than a shared one -- the two providers' payload shapes genuinely
don't line up onto the same columns.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import Connection

from wnba_engine.models.balldontlie_injuries import BdlInjuryEntry

_INSERT_SNAPSHOT = """
INSERT INTO balldontlie_injury_reports (
    player_id, team_id, status, return_date_text, comment, captured_at, source
) VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def insert_snapshots(
    conn: Connection,
    entries: Sequence[BdlInjuryEntry],
    *,
    player_id_by_external_id: Mapping[str, int],
    team_id_by_abbreviation: Mapping[str, int],
    source: str = "balldontlie",
) -> int:
    """Append one row per entry whose player and team both resolved.

    Entries missing either mapping are silently excluded here rather than
    inserted with a NULL foreign key -- the caller is expected to have
    already logged why a given entry didn't resolve (same contract as
    injury_repo.insert_snapshots).
    """
    rows = [
        (
            player_id_by_external_id[entry.player.external_id],
            team_id_by_abbreviation[entry.team.abbreviation],
            entry.status,
            entry.return_date_text,
            entry.comment,
            entry.captured_at,
            source,
        )
        for entry in entries
        if entry.player.external_id in player_id_by_external_id
        and entry.team.abbreviation in team_id_by_abbreviation
    ]
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(_INSERT_SNAPSHOT, rows)
    return len(rows)
