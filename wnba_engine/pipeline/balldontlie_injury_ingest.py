"""balldontlie injury report snapshot ingestion: paid API (GOAT tier), a
second live current-state source alongside ESPN's -- see
db/migrations/0016_balldontlie_injury_reports.sql for why it writes to a
separate table, and db/migrations/0005_injury_reports.sql for the
append-only-snapshot philosophy this mirrors.

Current-state only, same as injury_ingest.py's ESPN sweep -- every run
captures a fresh league-wide snapshot; there's no date/season filter on
this endpoint (only team_ids[]/player_ids[], per the OpenAPI spec) and
therefore no historical version of this feed to backfill.

Each row resolves its player via resolve_or_create_player_by_name (same
name-based crosswalk every other balldontlie pipeline uses, letting a
balldontlie-only injured player originate a brand-new canonical identity)
and its team via find_team_by_abbreviation (read-only, same as the
standings pipeline -- every real WNBA team is already known from box-score
ingestion, so an unresolved abbreviation is logged and skipped rather than
originating a new team row).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.injuries_parser import parse_injuries
from wnba_engine.db.pool import Database
from wnba_engine.repositories import balldontlie_injury_repo, entity_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 50  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlInjuryIngestResult:
    pages_fetched: int = 0
    entries_seen: int = 0
    entries_inserted: int = 0
    unresolved_teams: int = 0


def snapshot_current_injuries(db: Database, client: BalldontlieClient) -> BdlInjuryIngestResult:
    captured_at = datetime.now(UTC)
    result = BdlInjuryIngestResult()
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_player_injuries_page(cursor=cursor, per_page=PAGE_SIZE)
        entries = parse_injuries(payload, captured_at=captured_at)
        result = replace(
            result,
            pages_fetched=result.pages_fetched + 1,
            entries_seen=result.entries_seen + len(entries),
        )

        with db.connection() as conn:
            team_id_by_abbreviation: dict[str, int] = {}
            player_id_by_external_id: dict[str, int] = {}
            resolvable_entries = []
            for entry in entries:
                team_id = team_id_by_abbreviation.get(
                    entry.team.abbreviation
                ) or entity_repo.find_team_by_abbreviation(conn, entry.team.abbreviation)
                if team_id is None:
                    logger.warning(
                        "unresolved team abbreviation=%s for balldontlie injury -- skipping",
                        entry.team.abbreviation,
                    )
                    result = replace(result, unresolved_teams=result.unresolved_teams + 1)
                    continue
                team_id_by_abbreviation[entry.team.abbreviation] = team_id
                player_id_by_external_id[entry.player.external_id] = (
                    entity_repo.resolve_or_create_player_by_name(
                        conn,
                        SOURCE,
                        entry.player.external_id,
                        entry.player.full_name,
                        entry.player.position,
                        entry.player.height,
                        entry.player.weight,
                        entry.player.jersey_number,
                        entry.player.college,
                        entry.player.age,
                    )
                )
                resolvable_entries.append(entry)

            inserted = balldontlie_injury_repo.insert_snapshots(
                conn,
                resolvable_entries,
                player_id_by_external_id=player_id_by_external_id,
                team_id_by_abbreviation=team_id_by_abbreviation,
                source=SOURCE,
            )
            result = replace(result, entries_inserted=result.entries_inserted + inserted)
            conn.commit()

        if len(entries) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result

    logger.warning("balldontlie injuries sweep exceeded %d pages", MAX_PAGES)
    return result


def _next_cursor(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, int) else None
