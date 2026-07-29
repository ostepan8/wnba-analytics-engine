"""End-to-end: replayed captures -> real Postgres.

Uses the same live-captured Kalshi/Polymarket fixtures the parser tests
use, wrapped in the capture-file envelope, so this exercises the real
matching and persistence path rather than a stub.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wnba_engine.models.games import TeamRef
from wnba_engine.pipeline.market_capture_ingest import ingest_captures
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

CAPTURED_AT = datetime(2026, 7, 20, 15, 30, tzinfo=UTC)


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())


def _write(directory: Path, provider: str, pages: list[object], stamp: str) -> None:
    target = directory / provider
    target.mkdir(parents=True, exist_ok=True)
    with gzip.open(target / f"{stamp}.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(
            {
                "schema_version": 1,
                "provider": provider,
                "captured_at": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T"
                f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z",
                "pages": pages,
            },
            handle,
        )


def _seed_captures(directory: Path, stamp: str = "20260720T153000Z") -> None:
    _write(
        directory,
        "kalshi",
        [
            {"series": load_fixture("kalshi_series.json")},
            {
                "series_ticker": "KXWNBAGAME",
                "cursor": None,
                "payload": load_fixture("kalshi_markets.json"),
            },
        ],
        stamp,
    )
    _write(
        directory,
        "polymarket",
        [{"offset": 0, "payload": load_fixture("polymarket_events.json")}],
        stamp,
    )


def test_replay_stamps_the_recorded_capture_time_not_now(clean_db, tmp_path):
    """The correctness property the whole design rests on: a file
    recorded days ago must land where it actually belongs in the time
    series, not at ingest o'clock."""
    _seed_captures(tmp_path)

    result = ingest_captures(clean_db, tmp_path)

    assert result.files_ingested == 2
    assert result.snapshots_inserted > 0

    with clean_db.connection() as conn:
        stamps = conn.execute(
            "SELECT DISTINCT captured_at FROM market_price_snapshots"
        ).fetchall()

    assert [row[0] for row in stamps] == [CAPTURED_AT]


def test_replay_is_idempotent_via_the_unique_constraint(clean_db, tmp_path):
    """Re-reading the whole archive must insert nothing -- what makes
    --all safe after a parser improvement."""
    _seed_captures(tmp_path)

    first = ingest_captures(clean_db, tmp_path, replay_all=True)
    second = ingest_captures(clean_db, tmp_path, replay_all=True)

    assert first.snapshots_inserted > 0
    assert second.files_ingested == 2  # re-read...
    assert second.snapshots_inserted == 0  # ...and wrote nothing


def test_high_water_mark_skips_already_loaded_files(clean_db, tmp_path):
    _seed_captures(tmp_path)
    ingest_captures(clean_db, tmp_path)

    again = ingest_captures(clean_db, tmp_path)

    assert again.files_skipped_old == 2
    assert again.files_ingested == 0


def test_a_newer_capture_still_loads_after_a_high_water_mark(clean_db, tmp_path):
    """The skip must be a high-water mark, not "seen this directory"."""
    _seed_captures(tmp_path, stamp="20260720T153000Z")
    ingest_captures(clean_db, tmp_path)

    _seed_captures(tmp_path, stamp="20260721T153000Z")
    later = ingest_captures(clean_db, tmp_path)

    assert later.files_ingested == 2
    assert later.snapshots_inserted > 0


def test_a_corrupt_file_does_not_abort_the_rest_of_the_archive(clean_db, tmp_path):
    """A truncated rsync must cost one file, not the whole sync."""
    _seed_captures(tmp_path)
    (tmp_path / "kalshi" / "20260721T000000Z.json.gz").write_bytes(b"truncated")

    result = ingest_captures(clean_db, tmp_path)

    assert result.files_failed == 1
    assert result.files_ingested == 2
    assert result.snapshots_inserted > 0


def test_empty_capture_directory_is_a_no_op(clean_db, tmp_path):
    result = ingest_captures(clean_db, tmp_path)

    assert result.files_seen == 0
    assert result.snapshots_inserted == 0


def _seed_injury_teams(conn) -> None:
    """The injury pipeline resolves teams by ESPN id, so they must already
    exist -- exactly as they would from a scoreboard sync in the real
    pipeline."""
    for external_id, name in (("20", "Atlanta Dream"), ("6", "Los Angeles Sparks")):
        entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id=external_id, name=name, abbreviation=name[:3].upper())
        )


def test_espn_injury_captures_replay_with_their_recorded_time(clean_db, tmp_path):
    """ESPN's injury endpoint is current-state-only with no historical
    version, so captures are the only way to build history -- and each
    must land at the moment it was actually observed."""
    _write(
        tmp_path,
        "espn-injuries",
        [{"page": 0, "payload": load_fixture("espn_injuries.json")}],
        "20260720T153000Z",
    )
    with clean_db.connection() as conn:
        _seed_injury_teams(conn)
        conn.commit()

    result = ingest_captures(clean_db, tmp_path)

    assert result.files_ingested == 1
    assert result.snapshots_inserted > 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source, captured_at FROM injury_reports"
        ).fetchall()

    # Same source the LIVE job writes -- one feed's history, not two.
    assert [(r[0], r[1]) for r in rows] == [("espn", CAPTURED_AT)]


def test_espn_injury_replay_is_idempotent(clean_db, tmp_path):
    _write(
        tmp_path,
        "espn-injuries",
        [{"page": 0, "payload": load_fixture("espn_injuries.json")}],
        "20260720T153000Z",
    )
    with clean_db.connection() as conn:
        _seed_injury_teams(conn)
        conn.commit()

    first = ingest_captures(clean_db, tmp_path, replay_all=True)
    second = ingest_captures(clean_db, tmp_path, replay_all=True)

    assert first.snapshots_inserted > 0
    assert second.snapshots_inserted == 0
