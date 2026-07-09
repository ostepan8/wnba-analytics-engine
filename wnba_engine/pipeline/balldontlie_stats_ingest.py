"""balldontlie TRADITIONAL box score stats ingestion: paid API (GOAT
tier), per-player and per-team points/rebounds/assists/etc. for the same
games ESPN's box scores already cover.

Unlike balldontlie_advanced_stats_ingest.py (offensive/defensive rating,
PIE, four factors -- data ESPN has no equivalent for), this is NOT meant
to replace or extend ESPN as the box-score source. It writes into the
SAME team_game_stats/player_game_stats tables ESPN already populates,
just with source='balldontlie' -- those tables were designed from the
start to hold multiple providers' box scores side by side (see
db/migrations/0002_box_scores.sql's PRIMARY KEY (game_id, ..., source)).
The point is purely to give a future validation check a second,
independent source of the same traditional stats to cross-verify ESPN's
box scores against.

Three phases per season, in this order:
1. Resolve every balldontlie game to our canonical games table via
   team+date matching (balldontlie_game_resolution, shared with every
   other per-game balldontlie pipeline).
2. Ingest per-team traditional stats.
3. Ingest per-player traditional stats.

Both stat phases reuse stats_repo.upsert_team_game_stats /
upsert_player_game_stats -- the SAME functions ESPN's box-score ingestion
already calls with source='espn' -- and the SAME
entity_repo.find_team_by_abbreviation / resolve_or_create_player_by_name
identity resolution balldontlie_advanced_stats_ingest.py already uses, so
a balldontlie player/team here resolves onto the SAME canonical row ESPN
originated rather than forking a duplicate identity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.stats_parser import parse_player_stats, parse_team_stats
from wnba_engine.db.pool import Database
from wnba_engine.pipeline.balldontlie_game_resolution import resolve_games_for_season
from wnba_engine.repositories import entity_repo, stats_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 200  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlStatsIngestResult:
    games_seen: int = 0
    games_resolved: int = 0
    games_unresolved: int = 0
    team_rows_seen: int = 0
    team_rows_inserted: int = 0
    unresolved_games_for_team_stats: int = 0
    unresolved_teams_for_team_stats: int = 0
    player_rows_seen: int = 0
    player_rows_inserted: int = 0
    unresolved_games_for_player_stats: int = 0
    unresolved_teams_for_player_stats: int = 0


def backfill_season(db: Database, client: BalldontlieClient, season: int) -> BdlStatsIngestResult:
    game_resolution = resolve_games_for_season(db, client, season)
    result = BdlStatsIngestResult(
        games_seen=game_resolution.games_seen,
        games_resolved=game_resolution.games_resolved,
        games_unresolved=game_resolution.games_unresolved,
    )
    result = _ingest_team_stats(db, client, season, result)
    return _ingest_player_stats(db, client, season, result)


def _ingest_team_stats(
    db: Database, client: BalldontlieClient, season: int, result: BdlStatsIngestResult
) -> BdlStatsIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_team_stats_page(season, cursor=cursor, per_page=PAGE_SIZE)
        rows = parse_team_stats(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, team_rows_seen=result.team_rows_seen + 1)
                game_id = entity_repo.lookup_internal_id(
                    conn, SOURCE, entity_repo.ENTITY_GAME, row.game.external_id
                )
                if game_id is None:
                    logger.warning(
                        "unresolved balldontlie game external_id=%s for team stats row -- skipping",
                        row.game.external_id,
                    )
                    result = replace(
                        result,
                        unresolved_games_for_team_stats=result.unresolved_games_for_team_stats + 1,
                    )
                    continue
                team_id = entity_repo.find_team_by_abbreviation(conn, row.team.abbreviation)
                if team_id is None:
                    logger.warning(
                        "unresolved team abbreviation=%s for balldontlie team stats -- skipping",
                        row.team.abbreviation,
                    )
                    result = replace(
                        result,
                        unresolved_teams_for_team_stats=result.unresolved_teams_for_team_stats + 1,
                    )
                    continue
                stats_repo.upsert_team_game_stats(
                    conn, game_id=game_id, team_id=team_id, source=SOURCE, box=row.box
                )
                result = replace(result, team_rows_inserted=result.team_rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning(
        "balldontlie team stats ingestion exceeded %d pages for season=%s", MAX_PAGES, season
    )
    return result


def _ingest_player_stats(
    db: Database, client: BalldontlieClient, season: int, result: BdlStatsIngestResult
) -> BdlStatsIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_player_stats_page(season, cursor=cursor, per_page=PAGE_SIZE)
        rows = parse_player_stats(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, player_rows_seen=result.player_rows_seen + 1)
                game_id = entity_repo.lookup_internal_id(
                    conn, SOURCE, entity_repo.ENTITY_GAME, row.game.external_id
                )
                if game_id is None:
                    logger.warning(
                        "unresolved balldontlie game external_id=%s for player "
                        "stats row -- skipping",
                        row.game.external_id,
                    )
                    result = replace(
                        result,
                        unresolved_games_for_player_stats=result.unresolved_games_for_player_stats
                        + 1,
                    )
                    continue
                team_id = entity_repo.find_team_by_abbreviation(conn, row.team.abbreviation)
                if team_id is None:
                    logger.warning(
                        "unresolved team abbreviation=%s for balldontlie player stats -- skipping",
                        row.team.abbreviation,
                    )
                    result = replace(
                        result,
                        unresolved_teams_for_player_stats=result.unresolved_teams_for_player_stats
                        + 1,
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
                stats_repo.upsert_player_game_stats(
                    conn,
                    game_id=game_id,
                    player_id=player_id,
                    team_id=team_id,
                    source=SOURCE,
                    line=row.box,
                )
                result = replace(result, player_rows_inserted=result.player_rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning(
        "balldontlie player stats ingestion exceeded %d pages for season=%s", MAX_PAGES, season
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
