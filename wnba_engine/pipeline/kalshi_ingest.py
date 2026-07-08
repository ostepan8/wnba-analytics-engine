"""Kalshi ingestion: WNBA series -> market price snapshots (append-only).

KXWNBAGAME markets (event tickers like KXWNBAGAME-26JUL09INDPHX) get their
game_id resolved at ingest time via kalshi.game_matching + a team/date
lookup against the canonical games table. Every other series (futures,
totals, props, ...) stays unmapped (NULL game_id) -- there's no single game
to resolve to, or resolving it needs a player crosswalk that doesn't exist
yet, and guessing would be worse than leaving it null.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.errors import WnbaEngineError
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.kalshi.game_matching import parse_matchup
from wnba_engine.kalshi.parser import (
    filter_wnba_series,
    parse_markets_page,
    parse_series_list,
)
from wnba_engine.models.markets import MarketSnapshot
from wnba_engine.repositories import entity_repo, market_repo

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SERIES = 50  # safety valve against a runaway cursor loop

# KXWNBAGAME markets settle well after the game (per observed close_time),
# so we anchor matching on the ticker's own date, not close_time. A 1-day
# window absorbs timezone/date-boundary slop around a game's actual start.
GAME_DATE_MATCH_WINDOW = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class KalshiIngestResult:
    series_processed: int = 0
    snapshots_inserted: int = 0
    failures: int = 0


def ingest_kalshi_wnba_markets(
    db: Database,
    client: KalshiClient,
    *,
    series_tickers: Sequence[str] | None = None,
    status: str = "open",
) -> KalshiIngestResult:
    """Snapshot current prices for every WNBA market.

    series_tickers overrides discovery (useful to snapshot just
    KXWNBAGAME); by default all WNBA series are discovered from /series.
    """
    if series_tickers is None:
        series = parse_series_list(client.fetch_sports_series())
        tickers = tuple(s.ticker for s in filter_wnba_series(series))
    else:
        tickers = tuple(series_tickers)

    captured_at = datetime.now(UTC)
    result = KalshiIngestResult()
    for ticker in tickers:
        try:
            inserted = _ingest_series(db, client, ticker, status=status, captured_at=captured_at)
        except WnbaEngineError:
            logger.exception("failed to ingest kalshi series ticker=%s", ticker)
            result = replace(result, failures=result.failures + 1)
            continue
        result = replace(
            result,
            series_processed=result.series_processed + 1,
            snapshots_inserted=result.snapshots_inserted + inserted,
        )
    return result


def _ingest_series(
    db: Database,
    client: KalshiClient,
    series_ticker: str,
    *,
    status: str,
    captured_at: datetime,
) -> int:
    inserted = 0
    cursor: str | None = None
    for _ in range(MAX_PAGES_PER_SERIES):
        payload = client.fetch_markets_page(series_ticker, status=status, cursor=cursor)
        snapshots, cursor = parse_markets_page(payload, captured_at=captured_at)
        if snapshots:
            with db.connection() as conn:
                game_id_by_market = _resolve_game_ids(conn, snapshots)
                inserted += market_repo.insert_snapshots(
                    conn, snapshots, game_id_by_market=game_id_by_market
                )
                conn.commit()
        if not cursor or not snapshots:
            return inserted
    logger.warning(
        "kalshi pagination exceeded %d pages for series=%s; stopping early",
        MAX_PAGES_PER_SERIES,
        series_ticker,
    )
    return inserted


def _resolve_game_ids(conn: Connection, snapshots: Sequence[MarketSnapshot]) -> dict[str, int]:
    """Map market_external_id -> canonical game id for KXWNBAGAME markets.

    Grouped by event_external_id first: a game's two outcome markets share
    one event ticker/title, so this is one parse + one lookup per game, not
    one per market row.
    """
    game_id_by_market: dict[str, int] = {}
    game_id_by_event: dict[str, int | None] = {}
    for snap in snapshots:
        if snap.event_external_id is None:
            continue
        if snap.event_external_id not in game_id_by_event:
            parsed = parse_matchup(snap.event_external_id, snap.title)
            if parsed is None:
                game_id_by_event[snap.event_external_id] = None
            else:
                game_date, team_a, team_b = parsed
                near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
                game_id_by_event[snap.event_external_id] = entity_repo.find_game_id_by_teams(
                    conn, team_a, team_b, near, window=GAME_DATE_MATCH_WINDOW
                )
        game_id = game_id_by_event[snap.event_external_id]
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return game_id_by_market
