"""Shared fixtures for integration tests: a real *test* Postgres database.

Requires a reachable test database (docker compose up -d provisions one —
see db/init/001-create-test-db.sql). Skips gracefully when unavailable.
Deliberately never touches WNBA_ENGINE_DATABASE_URL directly — that's the
real dev database, and truncating it by accident once already cost a full
historical backfill. Instead this connects to a derived '<db>_test'
database (or WNBA_ENGINE_TEST_DATABASE_URL if set) and hard-fails if that
database's name doesn't contain 'test', as a second guard against ever
pointing this at dev.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from wnba_engine.config import load_settings
from wnba_engine.db.migrate import run_migrations
from wnba_engine.db.pool import Database

_TABLES = (
    "injury_reports",
    "market_price_snapshots",
    "sportsbook_player_prop_odds",
    "sportsbook_game_odds",
    "game_plays",
    "player_shot_zone_stats",
    "team_shot_zone_stats",
    "player_advanced_stats",
    "team_standings_history",
    "team_standings",
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
