"""Historical injury backfill via the Internet Archive Wayback Machine.

This is the actual source of 2022-2026 historical injury data -- ESPN's
live /injuries API has none (see 0005_injury_reports.sql). Each Wayback
snapshot of espn.com/wnba/injuries is a genuine point-in-time record of
what ESPN's page showed on that date.

Resumable: a day with any row already captured is skipped before any
network fetch, so an interrupted run can restart without re-fetching
everything from archive.org.

Same-day fallback: a CDX-confirmed 200 can still fail at actual fetch time
(observed live: a "revisit" record pointing to a differently-timestamped
capture that was failing on archive.org's own storage backend). Rather than
counting the whole day as failed after one bad candidate, every 200-status
timestamp for that day is tried in order until one actually works.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.errors import WnbaEngineError
from wnba_engine.espn.wayback_client import WaybackClient
from wnba_engine.espn.wayback_injuries_parser import parse_wayback_injuries_page
from wnba_engine.models.injuries import WaybackInjuryEntry
from wnba_engine.repositories import entity_repo, injury_repo

logger = logging.getLogger(__name__)

# The injury_reports.source tag for these rows -- distinct from the crosswalk
# provider below, which must stay "espn": the player/team ids in an archived
# page are the SAME ESPN id space used by the live API and box scores, just
# observed via an archive instead of a live call. Resolving them under a
# different provider key would silently fork a parallel, disconnected
# identity for every player and team instead of reusing what already exists.
SOURCE = "espn-wayback"
CROSSWALK_PROVIDER = "espn"

_SELECT_ALREADY_CAPTURED_FOR_DAY_SQL = """
SELECT 1 FROM injury_reports
WHERE source = %s AND captured_at >= %s AND captured_at < %s
LIMIT 1
"""


@dataclass(frozen=True, slots=True)
class WaybackBackfillResult:
    snapshots_available: int = 0
    snapshots_already_captured: int = 0
    snapshots_processed: int = 0
    entries_inserted: int = 0
    unresolved_teams: int = 0
    failures: int = 0


def backfill_injury_history(
    db: Database, client: WaybackClient, since: date, until: date
) -> WaybackBackfillResult:
    timestamps = _parse_cdx_timestamps(client.fetch_snapshot_timestamps(since, until))
    candidates_by_day = _group_by_day(timestamps)
    result = WaybackBackfillResult(snapshots_available=len(candidates_by_day))

    for day in sorted(candidates_by_day):
        day_start = datetime.strptime(day, "%Y%m%d").replace(tzinfo=UTC)
        with db.connection() as conn:
            already_captured = conn.execute(
                _SELECT_ALREADY_CAPTURED_FOR_DAY_SQL,
                (SOURCE, day_start, day_start + timedelta(days=1)),
            ).fetchone()
        if already_captured:
            result = replace(
                result, snapshots_already_captured=result.snapshots_already_captured + 1
            )
            continue

        outcome = _ingest_day(db, client, day, candidates_by_day[day])
        if outcome is None:
            result = replace(result, failures=result.failures + 1)
            continue

        inserted, unresolved = outcome
        result = replace(
            result,
            snapshots_processed=result.snapshots_processed + 1,
            entries_inserted=result.entries_inserted + inserted,
            unresolved_teams=result.unresolved_teams + unresolved,
        )
    return result


def _ingest_day(
    db: Database, client: WaybackClient, day: str, candidates: list[str]
) -> tuple[int, int] | None:
    """Try each same-day candidate timestamp in order; returns the first
    one that actually succeeds, or None if every candidate failed."""
    last_error: WnbaEngineError | None = None
    for timestamp in candidates:
        captured_at = _parse_wayback_timestamp(timestamp)
        try:
            return _ingest_snapshot(db, client, timestamp, captured_at)
        except WnbaEngineError as exc:
            last_error = exc
            logger.warning(
                "wayback candidate timestamp=%s (day=%s) failed, trying next "
                "same-day alternate if any: %s",
                timestamp,
                day,
                exc,
            )
    logger.error(
        "all %d candidate(s) for day=%s failed; last error: %s", len(candidates), day, last_error
    )
    return None


def _group_by_day(timestamps: list[str]) -> dict[str, list[str]]:
    by_day: dict[str, list[str]] = defaultdict(list)
    for ts in sorted(timestamps):
        by_day[ts[:8]].append(ts)
    return dict(by_day)


def _ingest_snapshot(
    db: Database, client: WaybackClient, timestamp: str, captured_at: datetime
) -> tuple[int, int]:
    html = client.fetch_snapshot_html(timestamp)
    entries = parse_wayback_injuries_page(html, snapshot_captured_at=captured_at)

    player_id_by_external_id: dict[str, int] = {}
    team_id_by_key: dict[tuple[str | None, str], int] = {}
    unresolved = 0

    with db.connection() as conn:
        for entry in entries:
            key = (entry.team_abbreviation, entry.team_name)
            team_id = team_id_by_key.get(key) or _resolve_team(conn, entry)
            if team_id is None:
                logger.warning(
                    "unresolved team abbreviation=%s name=%s on wayback snapshot "
                    "timestamp=%s -- skipping",
                    entry.team_abbreviation,
                    entry.team_name,
                    timestamp,
                )
                unresolved += 1
                continue
            team_id_by_key[key] = team_id
            player_id_by_external_id[entry.player.external_id] = (
                entity_repo.resolve_or_create_player(conn, CROSSWALK_PROVIDER, entry.player)
            )

        inserted = injury_repo.insert_wayback_snapshots(
            conn,
            entries,
            player_id_by_external_id=player_id_by_external_id,
            team_id_by_key=team_id_by_key,
            source=SOURCE,
        )
        conn.commit()

    return inserted, unresolved


def _resolve_team(conn: Connection, entry: WaybackInjuryEntry) -> int | None:
    """Abbreviation first (fast, precise); fall back to team_name when the
    logo URL had none extractable (see wayback_injuries_parser)."""
    if entry.team_abbreviation is not None:
        team_id = entity_repo.find_team_by_abbreviation(conn, entry.team_abbreviation)
        if team_id is not None:
            return team_id
    return entity_repo.find_team_by_name(conn, entry.team_name)


def _parse_cdx_timestamps(payload: object) -> list[str]:
    if not isinstance(payload, list) or not payload:
        return []
    # Row 0 is the CDX header ("urlkey", "timestamp", ...); timestamp is column 1.
    return [row[1] for row in payload[1:] if isinstance(row, list) and len(row) > 1]


def _parse_wayback_timestamp(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
