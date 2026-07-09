"""balldontlie game-level sportsbook odds ingestion: paid API (GOAT tier),
moneyline/spread/total lines from real bookmakers.

See db/migrations/0014_balldontlie_odds.sql for the schema and why this is
a genuinely different concept from market_price_snapshots (prediction-market
contracts).

Confirmed live (see wnba_engine/balldontlie/odds_parser.py): /wnba/v1/odds
only carries a ROLLING RECENT WINDOW of games (the current/upcoming season),
not full historical archives -- every 2025-season date tried returned a
valid empty response, while 2026-season (current) dates returned real rows.
So this backfills a DATE RANGE (the endpoint's own `dates[]=` query
contract), mirroring espn_ingest.backfill's --since/--until shape, rather
than a --season shape like the other balldontlie pipelines use -- a season
shape would imply "this covers a whole season," which isn't true for odds.

Games are resolved via the SAME balldontlie game crosswalk
(balldontlie_game_resolution.resolve_games_for_season) the advanced-stats/
plays/shot-zone pipelines use -- this endpoint references the same
game_id space (verified live: game_ids seen here match /wnba/v1/games'
own ids for the same date). Resolved once per season touched by the date
range, up front, same phase-1/phase-2 structure as backfill_season in
balldontlie_advanced_stats_ingest.py (never nested inside a per-page
db.connection() block).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, timedelta

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.odds_parser import parse_game_odds
from wnba_engine.db.pool import Database
from wnba_engine.pipeline.balldontlie_game_resolution import resolve_games_for_season
from wnba_engine.repositories import entity_repo, odds_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 50  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlOddsIngestResult:
    dates_processed: int = 0
    rows_seen: int = 0
    rows_inserted: int = 0
    unresolved_games: int = 0


def backfill_date_range(
    db: Database, client: BalldontlieClient, since: date, until: date
) -> BdlOddsIngestResult:
    if since > until:
        raise ValueError("since must not be after until")

    for season in _seasons_touched(since, until):
        resolve_games_for_season(db, client, season)

    result = BdlOddsIngestResult()
    day = since
    while day <= until:
        result = replace(result, dates_processed=result.dates_processed + 1)
        result = _ingest_date(db, client, day, result)
        day += timedelta(days=1)
    return result


def _seasons_touched(since: date, until: date) -> tuple[int, ...]:
    # WNBA seasons run within one calendar year (May-Oct), so this is
    # almost always a single value -- but a range spanning a year boundary
    # (e.g. a --since/--until crossing Dec 31) touches two.
    return tuple(sorted({since.year, until.year}))


def _ingest_date(
    db: Database, client: BalldontlieClient, day: date, result: BdlOddsIngestResult
) -> BdlOddsIngestResult:
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_odds_page(day, cursor=cursor, per_page=PAGE_SIZE)
        rows = parse_game_odds(payload)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, rows_seen=result.rows_seen + 1)
                game_id = entity_repo.lookup_internal_id(
                    conn, SOURCE, entity_repo.ENTITY_GAME, row.game_external_id
                )
                if game_id is None:
                    logger.warning(
                        "unresolved balldontlie game external_id=%s for odds row -- skipping",
                        row.game_external_id,
                    )
                    result = replace(result, unresolved_games=result.unresolved_games + 1)
                    continue
                inserted = odds_repo.insert_game_odds(conn, game_id=game_id, source=SOURCE, row=row)
                if inserted:
                    result = replace(result, rows_inserted=result.rows_inserted + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning("balldontlie odds ingestion exceeded %d pages for date=%s", MAX_PAGES, day)
    return result


def _next_cursor(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, int) else None
