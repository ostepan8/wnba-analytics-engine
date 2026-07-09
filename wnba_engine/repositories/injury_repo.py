"""Injury report snapshot persistence. Append-only -- never updated.

The live ESPN source (see db/migrations/0005_injury_reports.sql) can't be
retroactively backfilled, only captured going forward. The Wayback source
below is how history actually gets filled in for 2022-2026: each row is a
real archived snapshot, not a live capture.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import Connection

from wnba_engine.models.injuries import InjuryReportEntry, WaybackInjuryEntry

_INSERT_SNAPSHOT = """
INSERT INTO injury_reports (
    espn_injury_id, player_id, team_id, status, status_type,
    injury_type, side, return_date, short_comment, long_comment,
    reported_at, captured_at, source
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_WAYBACK_SNAPSHOT = """
INSERT INTO injury_reports (
    espn_injury_id, player_id, team_id, status, status_type,
    injury_type, side, return_date, short_comment, long_comment,
    reported_at, captured_at, source
) VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, %s, NULL, %s, %s, %s)
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


def insert_wayback_snapshots(
    conn: Connection,
    entries: Sequence[WaybackInjuryEntry],
    *,
    player_id_by_external_id: Mapping[str, int],
    team_id_by_key: Mapping[tuple[str | None, str], int],
    source: str = "espn-wayback",
) -> int:
    """Append one row per entry whose player and team both resolved.

    team_id_by_key is keyed by (team_abbreviation, team_name) -- the same
    composite key the pipeline resolved each entry's team under (logo
    abbreviation when extractable, falling back to team_name), not by
    abbreviation alone: some snapshots have no extractable abbreviation at
    all (see wayback_injuries_parser._extract_abbreviation).

    injury_type/side/return_date are always NULL here: the archived page
    format never had those structured fields, only free text (stored in
    short_comment). espn_injury_id is synthesized (player + snapshot time)
    since this page format carries no per-note id.
    """
    rows = [
        (
            f"wayback:{entry.player.external_id}:{entry.captured_at.isoformat()}",
            player_id_by_external_id[entry.player.external_id],
            team_id_by_key[(entry.team_abbreviation, entry.team_name)],
            entry.status,
            entry.status_type,
            entry.description,
            entry.reported_at,
            entry.captured_at,
            source,
        )
        for entry in entries
        if entry.player.external_id in player_id_by_external_id
        and (entry.team_abbreviation, entry.team_name) in team_id_by_key
    ]
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(_INSERT_WAYBACK_SNAPSHOT, rows)
    return len(rows)
