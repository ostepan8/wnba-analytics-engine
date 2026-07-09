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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from wnba_engine.config import load_settings
from wnba_engine.db.migrate import run_migrations
from wnba_engine.db.pool import Database
from wnba_engine.errors import ProviderRequestError
from wnba_engine.models.games import GameStatus, ScoreboardGame, SeasonType, TeamRef
from wnba_engine.pipeline.balldontlie_advanced_stats_ingest import backfill_season
from wnba_engine.pipeline.espn_ingest import backfill, sync_date
from wnba_engine.pipeline.injury_ingest import ingest_current_injury_report
from wnba_engine.pipeline.kalshi_ingest import ingest_kalshi_wnba_markets
from wnba_engine.pipeline.polymarket_ingest import ingest_polymarket_wnba_markets
from wnba_engine.pipeline.wayback_injury_backfill import backfill_injury_history
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())


def load_text_fixture(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text()

_TABLES = (
    "injury_reports",
    "market_price_snapshots",
    "player_advanced_stats",
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


class FakeInjuriesEspnClient:
    def fetch_injuries(self) -> object:
        return load_fixture("espn_injuries.json")


def test_injury_ingestion_end_to_end(clean_db):
    # Only pre-seed LA Sparks (external_id "6"), matching how a real team
    # would already be known from box-score ingestion. Atlanta Dream (id
    # "20") is deliberately left unknown to exercise the unresolved-team
    # skip path in the same run.
    with clean_db.connection() as conn:
        entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="6", name="Los Angeles Sparks", abbreviation="LA")
        )
        conn.commit()

    result = ingest_current_injury_report(clean_db, FakeInjuriesEspnClient())
    assert result.entries_seen == 4
    assert result.entries_inserted == 2  # only LA's two entries resolved
    assert result.unresolved_teams == 2  # Atlanta's two entries, skipped

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT p.full_name, ir.status, ir.injury_type, ir.return_date "
            "FROM injury_reports ir JOIN players p ON p.id = ir.player_id "
            "ORDER BY p.full_name"
        ).fetchall()
    assert rows == [
        ("Cameron Brink", "Out", "Ankle", date(2026, 7, 13)),
        ("Kelsey Plum", "Out", "Lower Leg", date(2026, 7, 28)),
    ]

    # Append-only: a second capture adds rows, never overwrites/updates.
    ingest_current_injury_report(clean_db, FakeInjuriesEspnClient())
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM injury_reports").fetchone()[0]
    assert count == 4


_WAYBACK_TIMESTAMP = "20260101120000"


class FakeWaybackClient:
    def fetch_snapshot_timestamps(self, since: date, until: date) -> object:
        del since, until
        return [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            [
                "com,espn)/wnba/injuries",
                _WAYBACK_TIMESTAMP,
                "https://www.espn.com/wnba/injuries",
                "text/html",
                "200",
                "ABC123",
                "314579",
            ],
        ]

    def fetch_snapshot_html(self, timestamp: str) -> str:
        assert timestamp == _WAYBACK_TIMESTAMP
        return load_text_fixture("espn_wayback_injuries.html")


def test_wayback_injury_backfill_end_to_end(clean_db):
    # Only pre-seed Chicago Sky (abbreviation "CHI"), matching how a real
    # team would already be known from box-score ingestion. Connecticut Sun
    # ("CON") is deliberately left unknown to exercise the unresolved-team
    # skip path in the same run.
    with clean_db.connection() as conn:
        entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="11", name="Chicago Sky", abbreviation="CHI")
        )
        conn.commit()

    result = backfill_injury_history(
        clean_db, FakeWaybackClient(), date(2026, 1, 1), date(2026, 1, 1)
    )
    assert result.snapshots_available == 1
    assert result.snapshots_processed == 1
    assert result.snapshots_already_captured == 0
    assert result.failures == 0
    assert result.entries_inserted == 2  # only Chicago Sky's two entries resolved
    assert result.unresolved_teams == 2  # Connecticut Sun's two entries, skipped

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT p.full_name, ir.status, ir.source, ir.injury_type, ir.short_comment "
            "FROM injury_reports ir JOIN players p ON p.id = ir.player_id "
            "ORDER BY p.full_name"
        ).fetchall()
    assert rows[0][0] == "Angel Reese"
    assert rows[0][1] == "Out"
    assert rows[0][2] == "espn-wayback"
    assert rows[0][3] is None  # no structured injury_type in this page format
    assert "Reese (back)" in rows[0][4]

    # Resumable: rerunning the same range does no network re-fetch and adds
    # nothing new, since the snapshot's captured_at is already recorded.
    rerun = backfill_injury_history(
        clean_db, FakeWaybackClient(), date(2026, 1, 1), date(2026, 1, 1)
    )
    assert rerun.snapshots_already_captured == 1
    assert rerun.snapshots_processed == 0
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM injury_reports WHERE source = 'espn-wayback'"
        ).fetchone()[0]
    assert count == 2

    # Crosswalk correctness: the Wayback-resolved player must reuse the
    # SAME canonical player id as the live 'espn' provider, not fork a
    # parallel identity under 'espn-wayback'.
    with clean_db.connection() as conn:
        live_id = entity_repo.lookup_internal_id(conn, "espn", "player", "4433402")
        wayback_row_player_id = conn.execute(
            "SELECT player_id FROM injury_reports WHERE source = 'espn-wayback' "
            "AND espn_injury_id LIKE 'wayback:4433402:%'"
        ).fetchone()
    assert live_id is not None
    assert wayback_row_player_id[0] == live_id


class FakeWaybackClientGuidLogo:
    """Real observed case: a team's logo URL has no extractable
    abbreviation (GUID-based asset path, not the classic
    /teamlogos/wnba/<size>/<abbr>.png), so resolution must fall back to
    team_name."""

    def fetch_snapshot_timestamps(self, since: date, until: date) -> object:
        del since, until
        return [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            [
                "com,espn)/wnba/injuries",
                _WAYBACK_TIMESTAMP,
                "https://www.espn.com/wnba/injuries",
                "text/html",
                "200",
                "ABC123",
                "500",
            ],
        ]

    def fetch_snapshot_html(self, timestamp: str) -> str:
        assert timestamp == _WAYBACK_TIMESTAMP
        return (
            "<script>window['__espnfitt__']={\"page\": {\"content\": {\"injuries\": ["
            '{"displayName": "Chicago Sky", '
            '"logo": "https://a.espncdn.com/guid/170598de-f63a-3497-a04d-1fc514508f56/'
            'logos/primary_logo_on_white_color.png", '
            '"items": [{"type": {"name": "INJURY_STATUS_OUT"}, '
            '"athlete": {"name": "Angel Reese", '
            '"href": "https://www.espn.com/wnba/player/_/id/4433402/angel-reese", '
            '"position": "F"}, "statusDesc": "Out", '
            '"date": "Jun 6", "description": "Reese (back) is out."}]}'
            "]}}};</script>"
        )


def test_wayback_injury_backfill_falls_back_to_team_name_when_logo_unparseable(clean_db):
    with clean_db.connection() as conn:
        entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="11", name="Chicago Sky", abbreviation="CHI")
        )
        conn.commit()

    result = backfill_injury_history(
        clean_db, FakeWaybackClientGuidLogo(), date(2026, 1, 1), date(2026, 1, 1)
    )
    assert result.failures == 0
    assert result.unresolved_teams == 0
    assert result.entries_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT t.name FROM injury_reports ir JOIN teams t ON t.id = ir.team_id "
            "WHERE ir.source = 'espn-wayback'"
        ).fetchone()
    assert row[0] == "Chicago Sky"


_DAY_WITH_BROKEN_FIRST_CANDIDATE = "20240425010921"
_DAY_WITH_WORKING_SECOND_CANDIDATE = "20240425171335"


class FakeWaybackClientSameDayFallback:
    """Real observed case: the day's first CDX-confirmed-200 timestamp
    fails at actual fetch time (archive.org backend issue on that specific
    file), but a later same-day capture works fine. The pipeline must try
    the second candidate rather than counting the whole day as failed."""

    def __init__(self) -> None:
        self.attempted: list[str] = []

    def fetch_snapshot_timestamps(self, since: date, until: date) -> object:
        del since, until
        return [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            [
                "com,espn)/wnba/injuries",
                _DAY_WITH_BROKEN_FIRST_CANDIDATE,
                "https://www.espn.com/wnba/injuries",
                "text/html",
                "200",
                "BROKEN123",
                "50000",
            ],
            [
                "com,espn)/wnba/injuries",
                _DAY_WITH_WORKING_SECOND_CANDIDATE,
                "https://www.espn.com/wnba/injuries",
                "text/html",
                "200",
                "WORKING456",
                "50000",
            ],
        ]

    def fetch_snapshot_html(self, timestamp: str) -> str:
        self.attempted.append(timestamp)
        if timestamp == _DAY_WITH_BROKEN_FIRST_CANDIDATE:
            raise ProviderRequestError(
                "espn-wayback", "https://web.archive.org/...", "403 (simulated backend failure)"
            )
        assert timestamp == _DAY_WITH_WORKING_SECOND_CANDIDATE
        return (
            "<script>window['__espnfitt__']={\"page\": {\"content\": {\"injuries\": ["
            '{"displayName": "Chicago Sky", '
            '"logo": "https://a.espncdn.com/i/teamlogos/wnba/500/chi.png", '
            '"items": [{"type": {"name": "INJURY_STATUS_OUT"}, '
            '"athlete": {"name": "Angel Reese", '
            '"href": "https://www.espn.com/wnba/player/_/id/4433402/angel-reese", '
            '"position": "F"}, "statusDesc": "Out", '
            '"date": "Jun 6", "description": "Reese (back) is out."}]}'
            "]}}};</script>"
        )


def test_wayback_injury_backfill_tries_same_day_alternate_when_first_candidate_fails(clean_db):
    with clean_db.connection() as conn:
        entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="11", name="Chicago Sky", abbreviation="CHI")
        )
        conn.commit()

    fake_client = FakeWaybackClientSameDayFallback()
    result = backfill_injury_history(
        clean_db, fake_client, date(2024, 4, 25), date(2024, 4, 25)
    )
    assert fake_client.attempted == [
        _DAY_WITH_BROKEN_FIRST_CANDIDATE,
        _DAY_WITH_WORKING_SECOND_CANDIDATE,
    ]
    assert result.snapshots_available == 1  # one DAY, not one per candidate
    assert result.snapshots_processed == 1
    assert result.failures == 0
    assert result.entries_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT captured_at FROM injury_reports WHERE source = 'espn-wayback'"
        ).fetchone()
    # captured_at reflects the candidate that actually succeeded, not the
    # broken first one.
    assert row[0].strftime("%Y%m%d%H%M%S") == _DAY_WITH_WORKING_SECOND_CANDIDATE


class FakeWaybackClientAllCandidatesFail:
    def fetch_snapshot_timestamps(self, since: date, until: date) -> object:
        del since, until
        return [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            [
                "com,espn)/wnba/injuries",
                "20240425010921",
                "https://www.espn.com/wnba/injuries",
                "text/html",
                "200",
                "BROKEN1",
                "50000",
            ],
            [
                "com,espn)/wnba/injuries",
                "20240425171335",
                "https://www.espn.com/wnba/injuries",
                "text/html",
                "200",
                "BROKEN2",
                "50000",
            ],
        ]

    def fetch_snapshot_html(self, timestamp: str) -> str:
        raise ProviderRequestError(
            "espn-wayback", "https://web.archive.org/...", "403 (simulated backend failure)"
        )


def test_wayback_injury_backfill_counts_one_failure_when_all_same_day_candidates_fail(clean_db):
    result = backfill_injury_history(
        clean_db, FakeWaybackClientAllCandidatesFail(), date(2024, 4, 25), date(2024, 4, 25)
    )
    assert result.snapshots_available == 1
    assert result.failures == 1  # one failure for the DAY, not one per exhausted candidate
    assert result.snapshots_processed == 0


class FakeBalldontlieClient:
    """One game matching the ESPN fixture's NY vs SEA, 2025-07-06 game, and
    one advanced-stats row for Nneka Ogwumike (ESPN external_id '1068' in
    the summary fixture) -- to prove the crosswalk lands on the SAME
    canonical player ESPN's box score already created."""

    def fetch_games_page(self, season: int, *, cursor: int | None = None, per_page: int = 100):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "id": 9001,
                    "date": "2025-07-06T17:00:00.000Z",
                    "home_team": {"id": 1, "full_name": "New York Liberty"},
                    "visitor_team": {"id": 2, "full_name": "Seattle Storm"},
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }

    def fetch_player_advanced_stats_page(
        self, season: int, *, cursor: int | None = None, per_page: int = 100
    ):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "id": 500001,
                    "player": {
                        "id": 777,
                        "first_name": "Nneka",
                        "last_name": "Ogwumike",
                        "position": "F",
                    },
                    "team": {"id": 2, "abbreviation": "SEA"},
                    "game": {"id": 9001, "date": "2025-07-06T17:00:00.000Z", "season": 2025},
                    "period": 0,
                    "stats": {
                        "misc": {"blocks": 0},
                        "usage": {"usage_percentage": 0.2},
                        "scoring": {"percentage_points2pt": 0.5},
                        "advanced": {
                            "minutes": "30:00",
                            "offensive_rating": 105.0,
                            "defensive_rating": 95.0,
                            "net_rating": 10.0,
                            "pace": 98.0,
                            "possessions": 60,
                            "true_shooting_percentage": 0.6,
                            "effective_field_goal_percentage": 0.55,
                            "usage_percentage": 0.2,
                            "assist_percentage": 0.1,
                            "assist_ratio": 12.0,
                            "assist_to_turnover": 1.5,
                            "turnover_ratio": 8.0,
                            "rebound_percentage": 0.15,
                            "offensive_rebound_percentage": 0.05,
                            "defensive_rebound_percentage": 0.2,
                            "pie": 0.15,
                        },
                        "four_factors": {
                            "free_throw_attempt_rate": 0.2,
                            "team_turnover_percentage": 0.12,
                            "opp_effective_field_goal_percentage": 0.5,
                            "opp_free_throw_attempt_rate": 0.18,
                            "opp_team_turnover_percentage": 0.14,
                            "opp_offensive_rebound_percentage": 0.25,
                        },
                    },
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }


def test_balldontlie_advanced_stats_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, incl. Ogwumike

    result = backfill_season(clean_db, FakeBalldontlieClient(), 2025)
    assert result.games_seen == 1
    assert result.games_resolved == 1
    assert result.games_unresolved == 0
    assert result.stat_rows_seen == 1
    assert result.stat_rows_inserted == 1
    assert result.unresolved_games_for_stats == 0
    assert result.unresolved_teams_for_stats == 0

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT p.full_name, pas.offensive_rating, pas.true_shooting_percentage, "
            "pas.pie, pas.misc_stats, t.abbreviation "
            "FROM player_advanced_stats pas "
            "JOIN players p ON p.id = pas.player_id "
            "JOIN teams t ON t.id = pas.team_id "
            "WHERE pas.source = 'balldontlie'"
        ).fetchone()
    assert row[0] == "Nneka Ogwumike"
    assert float(row[1]) == pytest.approx(105.0)
    assert float(row[2]) == pytest.approx(0.6)
    assert float(row[3]) == pytest.approx(0.15)
    assert row[4] == {"blocks": 0}
    assert row[5] == "SEA"

    # Crosswalk correctness: balldontlie's player id must resolve to the
    # SAME canonical player ESPN's box score already created (external_id
    # '1068' in the summary fixture), not a forked duplicate identity.
    with clean_db.connection() as conn:
        espn_player_id = entity_repo.lookup_internal_id(conn, "espn", "player", "1068")
        bdl_player_id = entity_repo.lookup_internal_id(conn, "balldontlie", "player", "777")
    assert espn_player_id is not None
    assert bdl_player_id == espn_player_id

    # Upserted, not append-only: re-running updates the same row.
    rerun = backfill_season(clean_db, FakeBalldontlieClient(), 2025)
    assert rerun.stat_rows_inserted == 1
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM player_advanced_stats WHERE source = 'balldontlie'"
        ).fetchone()[0]
    assert count == 1


def test_find_game_id_by_teams_matches_partial_expansion_team_names(clean_db):
    """Regression test: balldontlie's two newest (2026) expansion franchises
    have an empty city field on their end, so their full_name comes back as
    just "Tempo" or "Fire" -- a prefix-only match against our canonical
    "Toronto Tempo" / "Portland Fire" would miss this entirely."""
    with clean_db.connection() as conn:
        home_id = entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="900", name="Toronto Tempo", abbreviation="TOR")
        )
        away_id = entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="901", name="Portland Fire", abbreviation="POR")
        )
        entity_repo.upsert_game(
            conn,
            "espn",
            ScoreboardGame(
                external_id="9999",
                start_time=datetime(2026, 6, 3, 23, 30, tzinfo=UTC),
                season=2026,
                season_type=SeasonType.REGULAR_SEASON,
                status=GameStatus.FINAL,
                home_team=TeamRef(external_id="900", name="Toronto Tempo", abbreviation="TOR"),
                away_team=TeamRef(external_id="901", name="Portland Fire", abbreviation="POR"),
                home_score=80,
                away_score=75,
            ),
            home_team_id=home_id,
            away_team_id=away_id,
        )
        conn.commit()

        game_id = entity_repo.find_game_id_by_teams(
            conn,
            "Tempo",
            "Fire",
            datetime(2026, 6, 3, 23, 30, tzinfo=UTC),
            window=timedelta(hours=6),
        )
    assert game_id is not None
