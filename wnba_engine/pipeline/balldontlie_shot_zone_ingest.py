"""balldontlie shot-zone stats ingestion: paid API (GOAT tier). Season-
level aggregates, not per-game -- no game resolution needed here, unlike
advanced stats and play-by-play. Player rows resolve via the same
name-based crosswalk advanced-stats ingestion uses; team rows via
abbreviation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.shot_zone_parser import (
    parse_player_shot_zone_stats,
    parse_team_shot_zone_stats,
)
from wnba_engine.db.pool import Database
from wnba_engine.repositories import entity_repo, shot_zone_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 200  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlShotZoneIngestResult:
    player_rows_seen: int = 0
    player_rows_inserted: int = 0
    team_rows_seen: int = 0
    team_rows_inserted: int = 0
    unresolved_teams: int = 0


def backfill_season_shot_zones(
    db: Database, client: BalldontlieClient, season: int
) -> BdlShotZoneIngestResult:
    result = _ingest_player_shot_zones(db, client, season, BdlShotZoneIngestResult())
    return _ingest_team_shot_zones(db, client, season, result)


def _ingest_player_shot_zones(
    db: Database, client: BalldontlieClient, season: int, result: BdlShotZoneIngestResult
) -> BdlShotZoneIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_player_shot_zone_stats_page(
            season, cursor=cursor, per_page=PAGE_SIZE
        )
        rows = parse_player_shot_zone_stats(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, player_rows_seen=result.player_rows_seen + 1)
                team_id = (
                    entity_repo.find_team_by_abbreviation(conn, row.team.abbreviation)
                    if row.team is not None
                    else None
                )
                if row.team is not None and team_id is None:
                    logger.warning(
                        "unresolved team abbreviation=%s for balldontlie player shot "
                        "zone stats -- row still ingested with NULL team_id",
                        row.team.abbreviation,
                    )
                    result = replace(result, unresolved_teams=result.unresolved_teams + 1)
                player_id = entity_repo.resolve_or_create_player_by_name(
                    conn, SOURCE, row.player.external_id, row.player.full_name, row.player.position
                )
                shot_zone_repo.upsert_player_shot_zone_stats(
                    conn, player_id=player_id, team_id=team_id, source=SOURCE, stats=row
                )
                result = replace(result, player_rows_inserted=result.player_rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning(
        "balldontlie player shot zone ingestion exceeded %d pages for season=%s", MAX_PAGES, season
    )
    return result


def _ingest_team_shot_zones(
    db: Database, client: BalldontlieClient, season: int, result: BdlShotZoneIngestResult
) -> BdlShotZoneIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_team_shot_zone_stats_page(season, cursor=cursor, per_page=PAGE_SIZE)
        rows = parse_team_shot_zone_stats(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, team_rows_seen=result.team_rows_seen + 1)
                team_id = entity_repo.find_team_by_abbreviation(conn, row.team.abbreviation)
                if team_id is None:
                    logger.warning(
                        "unresolved team abbreviation=%s for balldontlie team shot "
                        "zone stats -- skipping",
                        row.team.abbreviation,
                    )
                    result = replace(result, unresolved_teams=result.unresolved_teams + 1)
                    continue
                shot_zone_repo.upsert_team_shot_zone_stats(
                    conn, team_id=team_id, source=SOURCE, stats=row
                )
                result = replace(result, team_rows_inserted=result.team_rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning(
        "balldontlie team shot zone ingestion exceeded %d pages for season=%s", MAX_PAGES, season
    )
    return result


def _next_cursor(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, int) else None
