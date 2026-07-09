"""Shared balldontlie game resolution: matches balldontlie's own game ids
to our canonical games via team+date matching, persisting the crosswalk.

Used by every balldontlie ingestion pipeline that needs a per-game
canonical game_id (advanced stats, play-by-play) -- shot-zone stats are
season-level aggregates and don't need this. Factored out rather than
duplicated once a second per-game consumer (play-by-play) needed the same
resolve-and-cache loop advanced-stats ingestion already had.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import timedelta

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.games_parser import parse_games
from wnba_engine.db.pool import Database
from wnba_engine.repositories import entity_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 200  # safety valve against a runaway cursor loop
PAGE_SIZE = 100
GAME_MATCH_WINDOW = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class GameResolutionResult:
    games_seen: int = 0
    games_resolved: int = 0
    games_unresolved: int = 0
    # (balldontlie external_id, canonical game id) for every resolved game
    # this season -- lets per-game consumers (play-by-play) iterate without
    # re-paginating /games or querying the crosswalk table by season (which
    # provider_entity_map doesn't index on).
    resolved: tuple[tuple[str, int], ...] = ()


def resolve_games_for_season(
    db: Database, client: BalldontlieClient, season: int
) -> GameResolutionResult:
    result = GameResolutionResult()
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_games_page(season, cursor=cursor, per_page=PAGE_SIZE)
        games = parse_games(payload)
        with db.connection() as conn:
            for game in games:
                result = replace(result, games_seen=result.games_seen + 1)
                existing = entity_repo.lookup_internal_id(
                    conn, SOURCE, entity_repo.ENTITY_GAME, game.external_id
                )
                if existing is not None:
                    result = replace(
                        result,
                        games_resolved=result.games_resolved + 1,
                        resolved=(*result.resolved, (game.external_id, existing)),
                    )
                    continue
                game_id = entity_repo.find_game_id_by_teams(
                    conn,
                    game.home_team_full_name,
                    game.away_team_full_name,
                    game.start_time,
                    window=GAME_MATCH_WINDOW,
                )
                if game_id is None:
                    logger.warning(
                        "could not match balldontlie game external_id=%s (%s vs %s, %s) "
                        "to a canonical game -- skipping",
                        game.external_id,
                        game.home_team_full_name,
                        game.away_team_full_name,
                        game.start_time,
                    )
                    result = replace(result, games_unresolved=result.games_unresolved + 1)
                    continue
                entity_repo.record_crosswalk_mapping(
                    conn, SOURCE, entity_repo.ENTITY_GAME, game.external_id, game_id
                )
                result = replace(
                    result,
                    games_resolved=result.games_resolved + 1,
                    resolved=(*result.resolved, (game.external_id, game_id)),
                )
            conn.commit()
        if len(games) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning("balldontlie game resolution exceeded %d pages for season=%s", MAX_PAGES, season)
    return result


def _next_cursor(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, int) else None
