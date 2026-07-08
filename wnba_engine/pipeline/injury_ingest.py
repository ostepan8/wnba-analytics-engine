"""Injury report ingestion: ESPN /injuries -> append-only snapshot rows.

Current-state only -- see 0005_injury_reports.sql. Every run captures a
real, fresh snapshot of today's report; there is no historical version of
this feed to backfill (verified directly: querying it in the context of a
years-old game still returns today's live data).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from wnba_engine.db.pool import Database
from wnba_engine.espn.client import EspnClient
from wnba_engine.espn.injuries_parser import parse_injuries
from wnba_engine.repositories import entity_repo, injury_repo

logger = logging.getLogger(__name__)

SOURCE = "espn"


@dataclass(frozen=True, slots=True)
class InjuryIngestResult:
    entries_seen: int = 0
    entries_inserted: int = 0
    unresolved_teams: int = 0


def ingest_current_injury_report(db: Database, client: EspnClient) -> InjuryIngestResult:
    captured_at = datetime.now(UTC)
    entries = parse_injuries(client.fetch_injuries(), captured_at=captured_at)

    player_id_by_external_id: dict[str, int] = {}
    team_id_by_external_id: dict[str, int] = {}
    unresolved_teams = 0

    with db.connection() as conn:
        for entry in entries:
            team_id = team_id_by_external_id.get(
                entry.team.external_id
            ) or entity_repo.lookup_internal_id(
                conn, SOURCE, entity_repo.ENTITY_TEAM, entry.team.external_id
            )
            if team_id is None:
                # This endpoint has no team abbreviation, so we can't safely
                # create a new canonical team row here (see models/injuries.py
                # docstring) -- skip rather than write incomplete data. Every
                # real WNBA team is already known from box-score ingestion,
                # so this should only fire for an exhibition/unknown entity.
                logger.warning(
                    "unresolved team on injury report external_id=%s name=%s -- skipping",
                    entry.team.external_id,
                    entry.team.name,
                )
                unresolved_teams += 1
                continue
            team_id_by_external_id[entry.team.external_id] = team_id
            player_id_by_external_id[
                entry.player.external_id
            ] = entity_repo.resolve_or_create_player(conn, SOURCE, entry.player)

        inserted = injury_repo.insert_snapshots(
            conn,
            entries,
            player_id_by_external_id=player_id_by_external_id,
            team_id_by_external_id=team_id_by_external_id,
            source=SOURCE,
        )
        conn.commit()

    return InjuryIngestResult(
        entries_seen=len(entries), entries_inserted=inserted, unresolved_teams=unresolved_teams
    )
