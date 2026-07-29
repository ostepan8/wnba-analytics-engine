"""Unit tests for replaying recorded prediction-market payloads.

The capture file format is a contract between a script deployed on
another machine (wnba_engine/market_capture/capture.py) and the replay
clients here. These tests pin that contract, since the two sides can't be
type-checked against each other.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.market_capture import SCHEMA_VERSION
from wnba_engine.market_capture.replay import (
    CaptureFile,
    ReplayKalshiClient,
    ReplayPolymarketClient,
    list_capture_files,
)

CAPTURED_AT = "2026-07-29T18:30:00Z"


def write_capture(
    directory: Path,
    provider: str,
    pages: list[object],
    *,
    name: str = "20260729T183000Z.json.gz",
    schema_version: int = SCHEMA_VERSION,
    captured_at: str = CAPTURED_AT,
) -> Path:
    target = directory / provider
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(
            {
                "schema_version": schema_version,
                "provider": provider,
                "captured_at": captured_at,
                "pages": pages,
            },
            handle,
        )
    return path


def test_capture_file_exposes_recorded_capture_time(tmp_path):
    """captured_at is authoritative -- it's what lands in the time series,
    never the ingest clock."""
    path = write_capture(tmp_path, "kalshi", [{"series": {"series": []}}])

    capture = CaptureFile(path)

    assert capture.captured_at == datetime(2026, 7, 29, 18, 30, tzinfo=UTC)
    assert capture.provider == "kalshi"


def test_capture_file_rejects_unknown_schema_version(tmp_path):
    """A format change must fail loudly rather than be silently
    misread -- the writer lives on another machine and can be upgraded
    independently."""
    path = write_capture(tmp_path, "kalshi", [], schema_version=999)

    with pytest.raises(ProviderValidationError):
        CaptureFile(path)


def test_capture_file_rejects_corrupt_archive(tmp_path):
    """A truncated rsync must not look like an empty capture."""
    target = tmp_path / "kalshi"
    target.mkdir(parents=True)
    path = target / "20260729T183000Z.json.gz"
    path.write_bytes(b"not actually gzip")

    with pytest.raises(ProviderValidationError):
        CaptureFile(path)


def test_kalshi_replay_serves_series_and_cursor_pages(tmp_path):
    path = write_capture(
        tmp_path,
        "kalshi",
        [
            {"series": {"series": [{"ticker": "KXWNBAGAME", "title": "WNBA Game"}]}},
            {
                "series_ticker": "KXWNBAGAME",
                "cursor": None,
                "payload": {"markets": [{"ticker": "A"}], "cursor": "next"},
            },
            {
                "series_ticker": "KXWNBAGAME",
                "cursor": "next",
                "payload": {"markets": [{"ticker": "B"}], "cursor": None},
            },
        ],
    )
    client = ReplayKalshiClient(CaptureFile(path))

    assert client.fetch_sports_series() == {
        "series": [{"ticker": "KXWNBAGAME", "title": "WNBA Game"}]
    }
    first = client.fetch_markets_page("KXWNBAGAME")
    second = client.fetch_markets_page("KXWNBAGAME", cursor="next")

    assert first["markets"] == [{"ticker": "A"}]
    assert second["markets"] == [{"ticker": "B"}]


def test_kalshi_replay_terminates_on_an_unrecorded_page(tmp_path):
    """An unrecorded page yields the same empty-and-cursorless shape the
    live walk stops on -- never a fabricated page."""
    path = write_capture(tmp_path, "kalshi", [{"series": {"series": []}}])
    client = ReplayKalshiClient(CaptureFile(path))

    page = client.fetch_markets_page("KXWNBAGAME", cursor="nonexistent")

    assert page == {"markets": [], "cursor": None}


def test_polymarket_replay_serves_offset_pages(tmp_path):
    path = write_capture(
        tmp_path,
        "polymarket",
        [
            {"offset": 0, "payload": [{"id": "1"}, {"id": "2"}]},
            {"offset": 2, "payload": [{"id": "3"}]},
        ],
    )
    client = ReplayPolymarketClient(CaptureFile(path))

    assert client.fetch_wnba_events_page(offset=0) == [{"id": "1"}, {"id": "2"}]
    assert client.fetch_wnba_events_page(offset=2) == [{"id": "3"}]
    # Unrecorded offset -> empty list, the live pipeline's stop signal.
    assert client.fetch_wnba_events_page(offset=99) == []


def test_replay_client_rejects_the_wrong_provider(tmp_path):
    """Guards against a mis-sorted file quietly ingesting as the wrong
    provider, which would corrupt both series."""
    path = write_capture(tmp_path, "polymarket", [])

    with pytest.raises(ProviderValidationError):
        ReplayKalshiClient(CaptureFile(path))


def test_capture_files_are_listed_oldest_first(tmp_path):
    """Replay order matters: resolution improves as canonical tables fill,
    so snapshots should be replayed against the schedule as it stood."""
    write_capture(tmp_path, "kalshi", [], name="20260729T183000Z.json.gz")
    write_capture(tmp_path, "kalshi", [], name="20260728T090000Z.json.gz")
    write_capture(tmp_path, "kalshi", [], name="20260729T120000Z.json.gz")

    names = [p.name for p in list_capture_files(tmp_path, "kalshi")]

    assert names == [
        "20260728T090000Z.json.gz",
        "20260729T120000Z.json.gz",
        "20260729T183000Z.json.gz",
    ]


def test_listing_a_missing_provider_directory_is_empty_not_an_error(tmp_path):
    assert list_capture_files(tmp_path, "kalshi") == ()
