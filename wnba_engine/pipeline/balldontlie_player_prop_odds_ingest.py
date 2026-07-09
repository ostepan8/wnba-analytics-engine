"""balldontlie player-prop sportsbook odds ingestion: paid API (GOAT tier).

See db/migrations/0014_balldontlie_odds.sql and
wnba_engine/pipeline/balldontlie_odds_ingest.py's module docstring for the
market_price_snapshots distinction and why odds backfills are windowed
rather than fully historical.

DIFFERENT backfill shape than balldontlie_odds_ingest's --since/--until:
/wnba/v1/odds/player_props requires a single `game_id=<int>` per request
(verified live -- see wnba_engine/balldontlie/player_prop_odds_parser.py),
not a date filter, so there's no way to ask this endpoint for "everything on
date D" directly. Rather than inventing a second date-scoped game-id
discovery mechanism (and double-hitting /wnba/v1/odds), this pipeline
reuses resolve_games_for_season's full per-season game list (the same
crosswalk balldontlie_odds_ingest.backfill_date_range already primes) and
queries player-prop odds for every game in the season -- games with no
cached props simply come back with an empty (not error) `data: []`
(confirmed live), so this is a --season-shaped command, matching the other
per-game balldontlie pipelines (advanced-stats, plays), even though odds
data itself only densely exists for the current season's recent window.

Player resolution is a straight provider_entity_map lookup
(entity_repo.lookup_internal_id), NOT resolve_or_create_player_by_name --
this payload carries only balldontlie's numeric player_id, no name, so a
never-before-seen player_id (i.e. no other balldontlie pipeline -- advanced
stats, shot zones -- has resolved it by name yet) has nothing to safely
create a canonical player row from, and is skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.player_prop_odds_parser import parse_player_prop_odds
from wnba_engine.db.pool import Database
from wnba_engine.pipeline.balldontlie_game_resolution import resolve_games_for_season
from wnba_engine.repositories import entity_repo, odds_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 50  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlPlayerPropOddsIngestResult:
    games_seen: int = 0
    games_resolved: int = 0
    games_unresolved: int = 0
    prop_rows_seen: int = 0
    prop_rows_inserted: int = 0
    unresolved_players: int = 0


def backfill_season(
    db: Database, client: BalldontlieClient, season: int
) -> BdlPlayerPropOddsIngestResult:
    game_resolution = resolve_games_for_season(db, client, season)
    result = BdlPlayerPropOddsIngestResult(
        games_seen=game_resolution.games_seen,
        games_resolved=game_resolution.games_resolved,
        games_unresolved=game_resolution.games_unresolved,
    )
    for game_external_id, game_id in game_resolution.resolved:
        result = _ingest_game_player_props(db, client, int(game_external_id), game_id, result)
    return result


def _ingest_game_player_props(
    db: Database,
    client: BalldontlieClient,
    game_external_id: int,
    game_id: int,
    result: BdlPlayerPropOddsIngestResult,
) -> BdlPlayerPropOddsIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_player_prop_odds_page(
            game_external_id, cursor=cursor, per_page=PAGE_SIZE
        )
        rows = parse_player_prop_odds(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, prop_rows_seen=result.prop_rows_seen + 1)
                player_id = entity_repo.lookup_internal_id(
                    conn, SOURCE, entity_repo.ENTITY_PLAYER, row.player_external_id
                )
                if player_id is None:
                    logger.warning(
                        "unresolved balldontlie player external_id=%s for prop-odds "
                        "row (game_id=%s) -- skipping",
                        row.player_external_id,
                        game_external_id,
                    )
                    result = replace(result, unresolved_players=result.unresolved_players + 1)
                    continue
                inserted = odds_repo.insert_player_prop_odds(
                    conn, game_id=game_id, player_id=player_id, source=SOURCE, row=row
                )
                if inserted:
                    result = replace(result, prop_rows_inserted=result.prop_rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning(
        "balldontlie player-prop-odds ingestion exceeded %d pages for game_id=%s",
        MAX_PAGES,
        game_external_id,
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
