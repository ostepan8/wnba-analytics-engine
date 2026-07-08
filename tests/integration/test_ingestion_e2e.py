"""End-to-end integration tests: migrations + pipeline -> real Postgres.

Requires a reachable Postgres at WNBA_ENGINE_DATABASE_URL (docker compose
up -d). Skips gracefully when the database is unavailable. Network calls
are replayed from fixtures via fake clients so results are deterministic.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import psycopg
import pytest

from wnba_engine.config import load_settings
from wnba_engine.db.migrate import run_migrations
from wnba_engine.db.pool import Database
from wnba_engine.pipeline.espn_ingest import backfill, sync_date
from wnba_engine.pipeline.kalshi_ingest import ingest_kalshi_wnba_markets
from wnba_engine.pipeline.polymarket_ingest import ingest_polymarket_wnba_markets

pytestmark = pytest.mark.integration

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())

_TABLES = (
    "market_price_snapshots",
    "player_game_stats",
    "team_game_stats",
    "provider_entity_map",
    "games",
    "players",
    "teams",
)


def _database_available(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="module")
def db():
    settings = load_settings()
    if not _database_available(settings.database_url):
        pytest.skip(
            "Postgres not reachable at WNBA_ENGINE_DATABASE_URL; run `docker compose up -d`"
        )
    database = Database(settings.database_url, min_size=1, max_size=2)
    run_migrations(database)
    yield database
    database.close()


@pytest.fixture
def clean_db(db):
    with db.connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
        conn.commit()
    return db


class FakeEspnClient:
    """Replays fixture payloads; only knows the game the summary fixture covers."""

    def fetch_scoreboard(self, day: date) -> object:
        payload = load_fixture("espn_scoreboard.json")
        return {"events": [e for e in payload["events"] if e["id"] == "401736228"]}

    def fetch_summary(self, event_id: str) -> object:
        assert event_id == "401736228"
        return load_fixture("espn_summary.json")


class FakeKalshiClient:
    def fetch_sports_series(self) -> object:
        return load_fixture("kalshi_series.json")

    def fetch_markets_page(self, series_ticker: str, **_: object) -> object:
        if series_ticker == "KXWNBAGAME":
            payload = load_fixture("kalshi_markets.json")
            return {"cursor": "", "markets": payload["markets"]}
        return {"cursor": "", "markets": []}


class FakePolymarketClient:
    def fetch_wnba_events_page(self, *, offset: int = 0, **_: object) -> object:
        return load_fixture("polymarket_events.json") if offset == 0 else []


def _count(db, table: str) -> int:
    with db.connection() as conn:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        return int(row[0])


def test_espn_ingestion_end_to_end(clean_db):
    result = sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))
    assert result.games_seen == 1
    assert result.games_upserted == 1
    assert result.box_scores_ingested == 1
    assert result.failures == 0

    assert _count(clean_db, "teams") == 2
    assert _count(clean_db, "players") == 8
    assert _count(clean_db, "games") == 1
    assert _count(clean_db, "team_game_stats") == 2
    assert _count(clean_db, "player_game_stats") == 8
    # crosswalk: 2 teams + 8 players + 1 game
    assert _count(clean_db, "provider_entity_map") == 11

    with clean_db.connection() as conn:
        game = conn.execute(
            "SELECT status, home_score, away_score, season FROM games"
        ).fetchone()
        assert game == ("final", 70, 79, 2025)
        dnp = conn.execute(
            "SELECT did_not_play, minutes, points FROM player_game_stats pgs "
            "JOIN provider_entity_map m ON m.internal_id = pgs.player_id "
            "AND m.entity_type = 'player' AND m.provider = 'espn' "
            "WHERE m.external_id = '3917453'"
        ).fetchone()
        assert dnp == (True, None, None)

    # Re-ingestion is idempotent for canonical/stat tables (upserts).
    rerun = sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))
    assert rerun.failures == 0
    assert _count(clean_db, "games") == 1
    assert _count(clean_db, "player_game_stats") == 8
    assert _count(clean_db, "provider_entity_map") == 11


def test_espn_backfill_sweeps_date_range(clean_db):
    result = backfill(clean_db, FakeEspnClient(), date(2025, 7, 5), date(2025, 7, 6))
    # Fake scoreboard returns the same single game for both dates; the
    # second pass upserts, so counts stay canonical.
    assert result.games_seen == 2
    assert result.games_upserted == 2
    assert result.failures == 0
    assert _count(clean_db, "games") == 1


def test_espn_backfill_rejects_inverted_range(clean_db):
    with pytest.raises(ValueError, match="must not be after"):
        backfill(clean_db, FakeEspnClient(), date(2025, 7, 6), date(2025, 7, 5))


def test_kalshi_ingestion_end_to_end(clean_db):
    result = ingest_kalshi_wnba_markets(clean_db, FakeKalshiClient())
    assert result.failures == 0
    assert result.series_processed == 3  # KXWNBATOTAL, KXWNBA, KXWNBAGAME
    assert result.snapshots_inserted == 3

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT provider, event_external_id, outcome, implied_probability, game_id "
            "FROM market_price_snapshots WHERE market_external_id = %s",
            ("KXWNBAGAME-26JUL09INDPHX-PHX",),
        ).fetchone()
    assert row[0] == "kalshi"
    assert row[1] == "KXWNBAGAME-26JUL09INDPHX"
    assert row[2] == "Phoenix"
    assert float(row[3]) == pytest.approx(0.405)
    assert row[4] is None  # game mapping deferred

    # Snapshots are append-only: a second run adds rows, never overwrites.
    ingest_kalshi_wnba_markets(clean_db, FakeKalshiClient())
    assert _count(clean_db, "market_price_snapshots") == 6


def test_polymarket_ingestion_end_to_end(clean_db):
    result = ingest_polymarket_wnba_markets(clean_db, FakePolymarketClient())
    assert result.events_seen == 2
    assert result.snapshots_inserted == 6

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT title, outcome, implied_probability, yes_bid FROM market_price_snapshots "
            "WHERE provider = 'polymarket' AND market_external_id = '1892489'"
        ).fetchone()
    assert row[0] == "Will Connecticut Sun win the 2026 WNBA Finals?"
    assert row[1] == "Connecticut Sun"
    assert float(row[2]) == pytest.approx(0.0005)
    assert row[3] is None
