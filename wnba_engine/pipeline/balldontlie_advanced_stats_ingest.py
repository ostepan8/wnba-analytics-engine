"""balldontlie advanced stats ingestion: paid API (GOAT tier), per-player-
per-game advanced box score stats (offensive/defensive rating, four
factors, usage, PIE, etc.) that no free source provides reliably -- ESPN
doesn't have it, and stats.wnba.com fights bot detection too aggressively
for a real pipeline.

Two phases per season, in this order:
1. Resolve every balldontlie game to our canonical games table via
   team+date matching (balldontlie_game_resolution, shared with
   play-by-play ingestion) -- balldontlie's own game ids are a different
   id space with no shared identifier to ESPN's.
2. Ingest the actual per-player advanced stats, using that crosswalk plus
   team-abbreviation and player-name resolution (resolve_or_create_player_by_name
   joins onto the SAME canonical player ESPN's box scores already created,
   rather than forking a duplicate identity under this provider).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from wnba_engine.balldontlie.advanced_stats_parser import parse_player_advanced_stats
from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.db.pool import Database
from wnba_engine.pipeline.balldontlie_game_resolution import resolve_games_for_season
from wnba_engine.repositories import advanced_stats_repo, entity_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 200  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlIngestResult:
    games_seen: int = 0
    games_resolved: int = 0
    games_unresolved: int = 0
    stat_rows_seen: int = 0
    stat_rows_inserted: int = 0
    unresolved_games_for_stats: int = 0
    unresolved_teams_for_stats: int = 0


def backfill_season(db: Database, client: BalldontlieClient, season: int) -> BdlIngestResult:
    game_resolution = resolve_games_for_season(db, client, season)
    result = BdlIngestResult(
        games_seen=game_resolution.games_seen,
        games_resolved=game_resolution.games_resolved,
        games_unresolved=game_resolution.games_unresolved,
    )
    return _ingest_advanced_stats(db, client, season, result)


def _ingest_advanced_stats(
    db: Database, client: BalldontlieClient, season: int, result: BdlIngestResult
) -> BdlIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_player_advanced_stats_page(season, cursor=cursor, per_page=PAGE_SIZE)
        rows = parse_player_advanced_stats(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, stat_rows_seen=result.stat_rows_seen + 1)
                game_id = entity_repo.lookup_internal_id(
                    conn, SOURCE, entity_repo.ENTITY_GAME, row.game.external_id
                )
                if game_id is None:
                    logger.warning(
                        "unresolved balldontlie game external_id=%s for advanced "
                        "stats row -- skipping",
                        row.game.external_id,
                    )
                    result = replace(
                        result, unresolved_games_for_stats=result.unresolved_games_for_stats + 1
                    )
                    continue
                team_id = entity_repo.find_team_by_abbreviation(conn, row.team.abbreviation)
                if team_id is None:
                    logger.warning(
                        "unresolved team abbreviation=%s for balldontlie advanced "
                        "stats -- skipping",
                        row.team.abbreviation,
                    )
                    result = replace(
                        result, unresolved_teams_for_stats=result.unresolved_teams_for_stats + 1
                    )
                    continue
                player_id = entity_repo.resolve_or_create_player_by_name(
                    conn,
                    SOURCE,
                    row.player.external_id,
                    row.player.full_name,
                    row.player.position,
                    row.player.height,
                    row.player.weight,
                    row.player.jersey_number,
                    row.player.college,
                    row.player.age,
                )
                advanced_stats_repo.upsert_player_advanced_stats(
                    conn,
                    game_id=game_id,
                    player_id=player_id,
                    team_id=team_id,
                    source=SOURCE,
                    stats=row,
                )
                result = replace(result, stat_rows_inserted=result.stat_rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning(
        "balldontlie advanced stats ingestion exceeded %d pages for season=%s", MAX_PAGES, season
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
