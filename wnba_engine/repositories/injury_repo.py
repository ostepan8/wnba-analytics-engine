"""Injury report snapshot persistence. Append-only -- never updated.

See db/migrations/0005_injury_reports.sql: this data can't be retroactively
backfilled, only captured going forward.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import Connection

from wnba_engine.models.injuries import InjuryReportEntry

_INSERT_SNAPSHOT = """
INSERT INTO injury_reports (
    espn_injury_id, player_id, team_id, status, status_type,
    injury_type, side, return_date, short_comment, long_comment,
    reported_at, captured_at, source
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def insert_snapshots(
    conn: Connection,
    entries: Sequence[InjuryReportEntry],
    *,
    player_id_by_external_id: Mapping[str, int],
    team_id_by_external_id: Mapping[str, int],
    source: str = "espn",
) -> int:
    """Append one row per entry whose player and team both resolved.

    Entries missing either mapping are silently excluded here rather than
    inserted with a NULL foreign key -- the caller is expected to have
    already logged why a given entry didn't resolve.
    """
    rows = [
        (
            entry.espn_injury_id,
            player_id_by_external_id[entry.player.external_id],
            team_id_by_external_id[entry.team.external_id],
            entry.status,
            entry.status_type,
            entry.injury_type,
            entry.side,
            entry.return_date,
            entry.short_comment,
            entry.long_comment,
            entry.reported_at,
            entry.captured_at,
            source,
        )
        for entry in entries
        if entry.player.external_id in player_id_by_external_id
        and entry.team.external_id in team_id_by_external_id
    ]
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(_INSERT_SNAPSHOT, rows)
    return len(rows)
