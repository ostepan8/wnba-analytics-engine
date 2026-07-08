"""Polymarket ingestion: WNBA-tagged events -> market price snapshots."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from wnba_engine.db.pool import Database
from wnba_engine.polymarket.client import PolymarketClient
from wnba_engine.polymarket.parser import parse_events
from wnba_engine.repositories import market_repo

logger = logging.getLogger(__name__)

MAX_PAGES = 50  # safety valve against a runaway offset loop


@dataclass(frozen=True, slots=True)
class PolymarketIngestResult:
    events_seen: int = 0
    snapshots_inserted: int = 0


def ingest_polymarket_wnba_markets(
    db: Database, client: PolymarketClient, *, include_closed: bool = False
) -> PolymarketIngestResult:
    """Snapshot current prices for every WNBA-tagged Polymarket market."""
    captured_at = datetime.now(UTC)
    events_seen = 0
    inserted = 0
    for _ in range(MAX_PAGES):
        payload = client.fetch_wnba_events_page(closed=include_closed, offset=events_seen)
        snapshots = parse_events(payload, captured_at=captured_at)
        # Advance by events actually received and stop only on an empty
        # page: Gamma may serve fewer than the requested limit per page.
        page_events = len(payload) if isinstance(payload, list) else 0
        if page_events == 0:
            return PolymarketIngestResult(events_seen=events_seen, snapshots_inserted=inserted)
        events_seen += page_events
        if snapshots:
            with db.connection() as conn:
                inserted += market_repo.insert_snapshots(conn, snapshots)
                conn.commit()
    logger.warning("polymarket pagination exceeded %d pages; stopping early", MAX_PAGES)
    return PolymarketIngestResult(events_seen=events_seen, snapshots_inserted=inserted)
