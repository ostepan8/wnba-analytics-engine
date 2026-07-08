"""Kalshi ingestion: WNBA series -> market price snapshots (append-only).

Game mapping (KXWNBAGAME event tickers -> canonical game ids) is deferred:
snapshots are stored with a NULL game_id and the event ticker preserved in
event_external_id, so mapping can be backfilled later without re-fetching.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from wnba_engine.db.pool import Database
from wnba_engine.errors import WnbaEngineError
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.kalshi.parser import (
    filter_wnba_series,
    parse_markets_page,
    parse_series_list,
)
from wnba_engine.repositories import market_repo

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SERIES = 50  # safety valve against a runaway cursor loop


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
                inserted += market_repo.insert_snapshots(conn, snapshots)
                conn.commit()
        if not cursor or not snapshots:
            return inserted
    logger.warning(
        "kalshi pagination exceeded %d pages for series=%s; stopping early",
        MAX_PAGES_PER_SERIES,
        series_ticker,
    )
    return inserted
