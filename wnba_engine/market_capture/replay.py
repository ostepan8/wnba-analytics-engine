"""Clients that serve recorded pages instead of making HTTP requests.

Each implements the same surface as its live counterpart, so
`ingest_kalshi_wnba_markets` / `ingest_polymarket_wnba_markets` run
against a captured file completely unchanged. That reuse is the point:
replay exercises the real matching, resolution, and persistence logic,
not a parallel implementation that could drift from it.

The recorded page lists mirror how each live client paginates:

- Kalshi walks a CURSOR. `pages` is
  `[{"series": <payload of /series?category=Sports>}]` followed by
  `{"series_ticker": ..., "cursor": <cursor used, null for the first
  page>, "payload": <that page>}` entries. Replay keys on
  `(series_ticker, cursor)`, so it reproduces the exact walk the live
  client performed.
- Polymarket walks an OFFSET. Entries are
  `{"offset": <int>, "payload": [...]}`; replay keys on offset and
  returns `[]` for an offset that was never recorded, which is precisely
  the "empty page" signal the live pipeline stops on.

A page the capture never recorded is therefore reported as absent rather
than fabricated, and ingestion terminates the same way it would have
live.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from wnba_engine.errors import ProviderValidationError
from wnba_engine.market_capture import (
    PROVIDER_KALSHI,
    PROVIDER_POLYMARKET,
    SCHEMA_VERSION,
)
from wnba_engine.parsing import parse_datetime_utc

PROVIDER = "market_capture"


class CaptureFile:
    """One decoded capture file: its provider, capture time, and pages."""

    def __init__(self, path: Path) -> None:
        self.path = path
        raw = _load(path)
        self.provider = _require_str(raw, "provider", path)
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ProviderValidationError(
                PROVIDER,
                f"unsupported schema_version {version!r} (expected {SCHEMA_VERSION})",
                context=str(path),
            )
        self.captured_at: datetime = parse_datetime_utc(
            _require_str(raw, "captured_at", path), PROVIDER, str(path)
        )
        pages = raw.get("pages")
        if not isinstance(pages, list):
            raise ProviderValidationError(
                PROVIDER, "pages must be a list", context=str(path)
            )
        self.pages: list[object] = pages


def _load(path: Path) -> Mapping[str, object]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise ProviderValidationError(
            PROVIDER, f"unreadable capture file: {exc}", context=str(path)
        ) from exc
    if not isinstance(raw, Mapping):
        raise ProviderValidationError(
            PROVIDER, "capture file must contain an object", context=str(path)
        )
    return raw


def _require_str(raw: Mapping[str, object], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderValidationError(
            PROVIDER, f"missing or non-string '{key}'", context=str(path)
        )
    return value


class ReplayKalshiClient:
    """Serves recorded Kalshi pages. Same surface as KalshiClient."""

    def __init__(self, capture: CaptureFile) -> None:
        if capture.provider != PROVIDER_KALSHI:
            raise ProviderValidationError(
                PROVIDER,
                f"expected a {PROVIDER_KALSHI} capture, got {capture.provider!r}",
                context=str(capture.path),
            )
        self._series: object = []
        self._markets: dict[tuple[str, str | None], object] = {}
        for entry in capture.pages:
            if not isinstance(entry, Mapping):
                continue
            if "series" in entry:
                self._series = entry["series"]
                continue
            ticker = entry.get("series_ticker")
            if isinstance(ticker, str):
                cursor = entry.get("cursor")
                key = (ticker, cursor if isinstance(cursor, str) else None)
                self._markets[key] = entry.get("payload")

    def fetch_sports_series(self) -> object:
        return self._series

    def fetch_markets_page(
        self,
        series_ticker: str,
        *,
        status: str = "open",
        cursor: str | None = None,
        limit: int = 200,
    ) -> object:
        del status, limit  # recorded at capture time, not re-selectable
        # An unrecorded page yields an empty market list with no cursor,
        # which is exactly how the live walk terminates.
        return self._markets.get((series_ticker, cursor), {"markets": [], "cursor": None})


class ReplayPolymarketClient:
    """Serves recorded Polymarket pages. Same surface as PolymarketClient."""

    def __init__(self, capture: CaptureFile) -> None:
        if capture.provider != PROVIDER_POLYMARKET:
            raise ProviderValidationError(
                PROVIDER,
                f"expected a {PROVIDER_POLYMARKET} capture, got {capture.provider!r}",
                context=str(capture.path),
            )
        self._pages: dict[int, object] = {}
        for entry in capture.pages:
            if isinstance(entry, Mapping) and isinstance(entry.get("offset"), int):
                self._pages[int(entry["offset"])] = entry.get("payload")

    def fetch_wnba_events_page(
        self, *, closed: bool = False, limit: int = 100, offset: int = 0
    ) -> object:
        del closed, limit  # recorded at capture time, not re-selectable
        # An empty list is the live pipeline's stop signal.
        return self._pages.get(offset, [])


def list_capture_files(directory: Path, provider: str) -> Sequence[Path]:
    """Capture files for one provider, oldest first.

    Chronological order matters on a fresh database: game/player
    resolution improves as the canonical tables fill in, and replaying
    oldest-first means a snapshot is resolved against the schedule as it
    stood, not after later files have taught the crosswalk more.
    """
    provider_dir = directory / provider
    if not provider_dir.is_dir():
        return ()
    return sorted(provider_dir.glob(f"*{'.json.gz'}"))
