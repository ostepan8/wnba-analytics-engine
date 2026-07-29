#!/usr/bin/env python3
"""Record raw Kalshi + Polymarket WNBA payloads to disk.

DEPLOYED VERBATIM to an always-on capture host (see DATA_INVENTORY.md).
It therefore uses ONLY the Python standard library and imports nothing
from wnba_engine -- the capture host has no repo, no uv, no database, and
no credentials. Both APIs are public and unauthenticated.

It lives inside the package anyway so the writer and the reader
(wnba_engine/market_capture/replay.py) sit next to each other: the file
format is a contract between them, and splitting it across two
repositories is how such contracts silently drift.

Output: one gzipped JSON file per provider per run, at
<root>/<provider>/<YYYYMMDDTHHMMSSZ>.json.gz. Pagination is recorded page
by page, keyed the way each live client walks it (Kalshi by cursor,
Polymarket by offset), so replay reproduces the exact same walk.

Deliberately dumb: it does not parse, filter, or interpret. Whatever the
provider said is what gets stored, so a future parser improvement can be
applied retroactively to the whole archive.

Usage:  python3 capture.py [--root ~/wnba-market-capture]
Exit code is non-zero if EITHER provider fails, so a scheduler surfaces
partial failure -- but each provider is attempted independently, so one
being down never costs the other's capture.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2/"
POLYMARKET_BASE = "https://gamma-api.polymarket.com/"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/"

KALSHI_MARKETS_PAGE_LIMIT = 200
POLYMARKET_PAGE_LIMIT = 100
MAX_PAGES = 50  # safety valve against a runaway cursor/offset loop

REQUEST_TIMEOUT_SECONDS = 30
MIN_REQUEST_INTERVAL_SECONDS = 0.2
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0

USER_AGENT = "wnba-analytics-engine market capture (read-only)"

_last_request_at = 0.0


def _get_json(base: str, path: str, params: dict[str, object]) -> object:
    """GET with naive rate limiting and bounded retries. Read-only."""
    global _last_request_at
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = urllib.parse.urljoin(base, path) + (f"?{query}" if query else "")

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        elapsed = time.monotonic() - _last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                _last_request_at = time.monotonic()
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            _last_request_at = time.monotonic()
            last_error = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
    raise RuntimeError(f"GET {url} failed after {MAX_ATTEMPTS} attempts: {last_error}")


def capture_kalshi() -> list[object]:
    """Series list, then every WNBA series' markets, page by page.

    Selection must be AT LEAST as broad as the engine's own
    filter_wnba_series (keyword in ticker OR title -- Kalshi has no WNBA
    category), because anything not captured is unrecoverable: these
    prices have no historical endpoint. A stricter rule here, e.g. a
    "KXWNBA" ticker prefix, would silently drop any series Kalshi names
    differently, and nobody would find out until the data was needed and
    permanently absent. Over-capturing costs a few KB; under-capturing
    costs history, so this errs wide and lets replay filter.
    """
    series_payload = _get_json(KALSHI_BASE, "series", {"category": "Sports"})
    pages: list[object] = [{"series": series_payload}]

    tickers = []
    if isinstance(series_payload, dict):
        for entry in series_payload.get("series") or []:
            if not isinstance(entry, dict):
                continue
            ticker = entry.get("ticker")
            title = entry.get("title")
            haystack = f"{ticker if isinstance(ticker, str) else ''} " + (
                title if isinstance(title, str) else ""
            )
            if isinstance(ticker, str) and "WNBA" in haystack.upper():
                tickers.append(ticker)

    for ticker in tickers:
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            payload = _get_json(
                KALSHI_BASE,
                "markets",
                {
                    "series_ticker": ticker,
                    "status": "open",
                    "limit": KALSHI_MARKETS_PAGE_LIMIT,
                    "cursor": cursor,
                },
            )
            pages.append({"series_ticker": ticker, "cursor": cursor, "payload": payload})
            next_cursor = payload.get("cursor") if isinstance(payload, dict) else None
            markets = payload.get("markets") if isinstance(payload, dict) else None
            if not next_cursor or not markets:
                break
            cursor = next_cursor
    return pages


def capture_polymarket() -> list[object]:
    """WNBA-tagged events, page by page, keyed by offset."""
    pages: list[object] = []
    offset = 0
    for _ in range(MAX_PAGES):
        payload = _get_json(
            POLYMARKET_BASE,
            "events",
            {
                "tag_slug": "wnba",
                "closed": "false",
                "limit": POLYMARKET_PAGE_LIMIT,
                "offset": offset,
            },
        )
        pages.append({"offset": offset, "payload": payload})
        count = len(payload) if isinstance(payload, list) else 0
        if count == 0:
            break
        offset += count
    return pages


def capture_espn_injuries() -> list[object]:
    """The league-wide injury report -- one unpaginated GET, no auth.

    Captured here for the same reason as the market feeds: ESPN serves
    only the CURRENT report and has no historical endpoint, so a day not
    recorded is a day lost. The Wayback Machine recovers only what
    archive.org happened to crawl, which across three months of the 2026
    season was 11 days.
    """
    return [{"page": 0, "payload": _get_json(ESPN_BASE, "injuries", {})}]


def write_capture(root: Path, provider: str, captured_at: datetime, pages: list[object]) -> Path:
    """Write atomically: a scheduler and an rsync can race, and a reader
    must never observe a half-written file."""
    directory = root / provider
    directory.mkdir(parents=True, exist_ok=True)
    name = captured_at.strftime("%Y%m%dT%H%M%SZ") + ".json.gz"
    final_path = directory / name
    temp_path = directory / f".{name}.partial"

    document = {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages": pages,
    }
    with gzip.open(temp_path, "wt", encoding="utf-8") as handle:
        json.dump(document, handle, separators=(",", ":"))
    temp_path.replace(final_path)
    return final_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="~/wnba-market-capture")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()

    captured_at = datetime.now(UTC).replace(microsecond=0)
    failures = 0
    feeds = (
        ("kalshi", capture_kalshi),
        ("polymarket", capture_polymarket),
        ("espn-injuries", capture_espn_injuries),
    )
    for provider, collect in feeds:
        try:
            pages = collect()
        except Exception as exc:  # noqa: BLE001 -- one provider must not sink the other
            print(f"[{captured_at:%Y-%m-%dT%H:%M:%SZ}] {provider}: FAILED {exc}", file=sys.stderr)
            failures += 1
            continue
        path = write_capture(root, provider, captured_at, pages)
        size_kb = path.stat().st_size / 1024
        print(
            f"[{captured_at:%Y-%m-%dT%H:%M:%SZ}] {provider}: "
            f"{len(pages)} page(s) -> {path.name} ({size_kb:.0f} KB)"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
