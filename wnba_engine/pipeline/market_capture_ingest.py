"""Load raw prediction-market captures recorded off-box.

Walks a capture directory (see wnba_engine/market_capture/) and replays
each file through the SAME ingest pipeline a live snapshot uses, with the
file's own recorded `captured_at` rather than the ingest wall-clock.

Idempotent twice over: a high-water mark skips files older than what's
already stored, and (provider, market_external_id, captured_at) is UNIQUE
so anything that slips through inserts nothing. Re-running after an
interrupted sync is therefore always safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from wnba_engine.db.pool import Database
from wnba_engine.errors import WnbaEngineError
from wnba_engine.market_capture import (
    PROVIDER_ESPN_INJURIES,
    PROVIDER_KALSHI,
    PROVIDER_POLYMARKET,
)
from wnba_engine.market_capture.replay import (
    CaptureFile,
    ReplayEspnInjuriesClient,
    ReplayKalshiClient,
    ReplayPolymarketClient,
    list_capture_files,
)
from wnba_engine.pipeline.injury_ingest import ingest_current_injury_report
from wnba_engine.pipeline.kalshi_ingest import ingest_kalshi_wnba_markets
from wnba_engine.pipeline.polymarket_ingest import ingest_polymarket_wnba_markets
from wnba_engine.repositories import injury_repo, market_repo

logger = logging.getLogger(__name__)

# Replayed injury captures are written under the SAME source the live
# snapshot job uses, because they are the same observation taken from the
# same endpoint -- just recorded somewhere that doesn't sleep. A separate
# source value would fork one feed's history into two.
INJURY_SOURCE = "espn"


@dataclass(frozen=True, slots=True)
class CaptureIngestResult:
    files_seen: int = 0
    files_ingested: int = 0
    files_skipped_old: int = 0
    files_failed: int = 0
    snapshots_inserted: int = 0


def ingest_captures(
    db: Database, directory: Path, *, replay_all: bool = False
) -> CaptureIngestResult:
    """Replay every capture in `directory` for both providers.

    `replay_all` ignores the high-water mark and re-reads the whole
    archive -- the reason captures are kept as raw payloads at all. Use
    it after improving a parser or a matcher: the historical record can
    be rebuilt from source rather than being frozen at whatever the code
    understood on the day it was recorded.
    """
    result = CaptureIngestResult()
    for provider in (PROVIDER_KALSHI, PROVIDER_POLYMARKET, PROVIDER_ESPN_INJURIES):
        result = _ingest_provider(db, directory, provider, replay_all, result)
    return result


def _ingest_provider(
    db: Database,
    directory: Path,
    provider: str,
    replay_all: bool,
    result: CaptureIngestResult,
) -> CaptureIngestResult:
    high_water: datetime | None = None
    if not replay_all:
        with db.connection() as conn:
            high_water = _high_water_mark(conn, provider)

    for path in list_capture_files(directory, provider):
        result = replace(result, files_seen=result.files_seen + 1)
        try:
            capture = CaptureFile(path)
        except WnbaEngineError as exc:
            # One corrupt file (a truncated rsync, say) must not abort the
            # rest of the archive.
            logger.warning("skipping unreadable capture %s: %s", path.name, exc)
            result = replace(result, files_failed=result.files_failed + 1)
            continue

        if high_water is not None and capture.captured_at <= high_water:
            result = replace(result, files_skipped_old=result.files_skipped_old + 1)
            continue

        try:
            inserted = _replay_one(db, capture, provider)
        except WnbaEngineError as exc:
            logger.warning("failed to ingest capture %s: %s", path.name, exc)
            result = replace(result, files_failed=result.files_failed + 1)
            continue

        result = replace(
            result,
            files_ingested=result.files_ingested + 1,
            snapshots_inserted=result.snapshots_inserted + inserted,
        )
    return result


def _high_water_mark(conn, provider: str) -> datetime | None:
    """Newest observation already stored for this feed.

    Injuries live in a different table than market prices, and under the
    source name the LIVE snapshot job already writes ('espn'), so a
    replayed capture and a live snapshot are the same kind of row -- not
    a parallel history.
    """
    if provider == PROVIDER_ESPN_INJURIES:
        return injury_repo.latest_captured_at(conn, INJURY_SOURCE)
    return market_repo.latest_captured_at(conn, provider)


def _replay_one(db: Database, capture: CaptureFile, provider: str) -> int:
    if provider == PROVIDER_KALSHI:
        return ingest_kalshi_wnba_markets(
            db, ReplayKalshiClient(capture), captured_at=capture.captured_at
        ).snapshots_inserted
    if provider == PROVIDER_POLYMARKET:
        return ingest_polymarket_wnba_markets(
            db, ReplayPolymarketClient(capture), captured_at=capture.captured_at
        ).snapshots_inserted
    return ingest_current_injury_report(
        db, ReplayEspnInjuriesClient(capture), captured_at=capture.captured_at
    ).entries_inserted
