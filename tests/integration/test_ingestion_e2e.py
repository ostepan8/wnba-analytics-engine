"""End-to-end integration tests: migrations + pipeline -> real Postgres.

Requires a reachable *test* Postgres database (docker compose up -d
provisions one — see db/init/001-create-test-db.sql). Skips gracefully when
unavailable. Network calls are replayed from fixtures via fake clients so
results are deterministic.

These tests TRUNCATE tables between runs (see `clean_db`). They deliberately
never touch WNBA_ENGINE_DATABASE_URL directly — that's the real dev database,
and truncating it by accident once already cost a full historical backfill.
Instead they connect to a derived '<db>_test' database (or
WNBA_ENGINE_TEST_DATABASE_URL if set) and hard-fail if that database's name
doesn't contain 'test', as a second guard against ever pointing this at dev.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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


def _test_database_url(dev_database_url: str) -> str:
    override = os.environ.get("WNBA_ENGINE_TEST_DATABASE_URL")
    if override:
        return override
    parts = urlsplit(dev_database_url)
    db_name = parts.path.lstrip("/")
    return urlunsplit(parts._replace(path=f"/{db_name}_test"))


def _database_available(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="module")
def db():
    test_url = _test_database_url(load_settings().database_url)
    db_name = urlsplit(test_url).path.lstrip("/")
    if "test" not in db_name:
        pytest.fail(
            f"refusing to run destructive integration tests against non-test "
            f"database {db_name!r}; set WNBA_ENGINE_TEST_DATABASE_URL to a "
            f"database with 'test' in its name"
        )
    if not _database_available(test_url):
        pytest.skip(
            f"Test Postgres database {db_name!r} not reachable; run "
            f"`docker compose up -d` (provisioned by db/init/001-create-test-db.sql)"
        )
    database = Database(test_url, min_size=1, max_size=2)
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
    assert row[4] is None  # no Indiana/Phoenix game seeded in this test's DB to map to

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


class FakeKalshiGameMarketClient:
    """A single KXWNBAGAME market for the same game FakeEspnClient seeds."""

    def fetch_sports_series(self) -> object:
        return {"series": [{"ticker": "KXWNBAGAME", "title": "Women's Pro Basketball Game"}]}

    def fetch_markets_page(self, series_ticker: str, **_: object) -> object:
        return {
            "cursor": "",
            "markets": [
                {
                    "ticker": "KXWNBAGAME-25JUL06SEANY-NY",
                    "event_ticker": "KXWNBAGAME-25JUL06SEANY",
                    "title": "Seattle vs New York winner?",
                    "status": "active",
                    "yes_bid_dollars": "0.4000",
                    "yes_ask_dollars": "0.4200",
                    "last_price_dollars": "0.4100",
                    "volume_fp": "100.00",
                    "open_interest_fp": "50.00",
                    "liquidity_dollars": "10.00",
                    "close_time": "2025-07-20T00:00:00Z",
                    "yes_sub_title": "New York",
                }
            ],
        }


def test_kalshi_game_mapping_resolves_via_teams_and_ticker_date(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = ingest_kalshi_wnba_markets(clean_db, FakeKalshiGameMarketClient())
    assert result.failures == 0
    assert result.snapshots_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT g.id FROM market_price_snapshots m JOIN games g ON g.id = m.game_id "
            "WHERE m.market_external_id = %s",
            ("KXWNBAGAME-25JUL06SEANY-NY",),
        ).fetchone()
    assert row is not None, "expected the seeded NY/SEA game to be mapped, got NULL game_id"


class FakePolymarketGameMarketClient:
    """A single team-matchup market for the same game FakeEspnClient seeds."""

    def fetch_wnba_events_page(self, *, offset: int = 0, **_: object) -> object:
        if offset != 0:
            return []
        return [
            {
                "id": "999001",
                "markets": [
                    {
                        "id": "999002",
                        "question": "Seattle Storm vs New York Liberty",
                        "bestBid": 0.45,
                        "bestAsk": 0.47,
                        "lastTradePrice": 0.46,
                        "outcomePrices": '["0.46", "0.54"]',
                        "groupItemTitle": "New York",
                        "volumeNum": 500,
                        "liquidityNum": 200,
                        "closed": False,
                        "active": True,
                        "endDateIso": "2025-07-08T00:00:00Z",
                    }
                ],
            }
        ]


def test_polymarket_game_mapping_resolves_via_teams_and_close_time(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = ingest_polymarket_wnba_markets(clean_db, FakePolymarketGameMarketClient())
    assert result.snapshots_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT g.id FROM market_price_snapshots m JOIN games g ON g.id = m.game_id "
            "WHERE m.market_external_id = %s",
            ("999002",),
        ).fetchone()
    assert row is not None, "expected the seeded NY/SEA game to be mapped, got NULL game_id"
