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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from wnba_engine.errors import ProviderRequestError
from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.models.games import GameStatus, ScoreboardGame, SeasonType, TeamRef
from wnba_engine.pipeline.balldontlie_advanced_stats_ingest import backfill_season
from wnba_engine.pipeline.balldontlie_odds_ingest import (
    backfill_date_range as backfill_odds_date_range,
)
from wnba_engine.pipeline.balldontlie_player_prop_odds_ingest import (
    backfill_season as backfill_player_prop_odds_season,
)
from wnba_engine.pipeline.balldontlie_plays_ingest import backfill_season_plays
from wnba_engine.pipeline.balldontlie_shot_zone_ingest import backfill_season_shot_zones
from wnba_engine.pipeline.balldontlie_standings_ingest import (
    backfill_season as backfill_standings_season,
)
from wnba_engine.pipeline.balldontlie_team_advanced_stats_ingest import (
    backfill_season as backfill_team_advanced_stats_season,
)
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


class FakeEspnClient:
    """Replays fixture payloads; only knows the game the summary fixture covers."""

    def fetch_scoreboard(self, day: date) -> object:
        payload = load_fixture("espn_scoreboard.json")
        return {"events": [e for e in payload["events"] if e["id"] == "401736228"]}

    def fetch_summary(self, event_id: str) -> object:
        assert event_id == "401736228"
        return load_fixture("espn_summary.json")


class FakeEspnClientWithGameInfo:
    """Replays a summary fixture that has ESPN's `gameInfo` block (venue +
    attendance) -- the plain FakeEspnClient's espn_summary.json fixture
    predates this feature and has no gameInfo key at all.
    """

    def fetch_scoreboard(self, day: date) -> object:
        payload = load_fixture("espn_scoreboard.json")
        return {"events": [e for e in payload["events"] if e["id"] == "401736227"]}

    def fetch_summary(self, event_id: str) -> object:
        assert event_id == "401736227"
        return load_fixture("espn_summary_with_game_info.json")


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
        game = conn.execute("SELECT status, home_score, away_score, season FROM games").fetchone()
        assert game == ("final", 70, 79, 2025)
        dnp = conn.execute(
            "SELECT did_not_play, minutes, points FROM player_game_stats pgs "
            "JOIN provider_entity_map m ON m.internal_id = pgs.player_id "
            "AND m.entity_type = 'player' AND m.provider = 'espn' "
            "WHERE m.external_id = '3917453'"
        ).fetchone()
        assert dnp == (True, None, None)
        # espn_summary.json (this fixture) predates gameInfo and has no such
        # key at all -- parse_summary fails open, so these stay NULL.
        venue = conn.execute("SELECT venue_name, attendance FROM games").fetchone()
        assert venue == (None, None)
        officials_count = conn.execute("SELECT count(*) FROM game_officials").fetchone()
        assert officials_count == (0,)

    # Re-ingestion is idempotent for canonical/stat tables (upserts).
    rerun = sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))
    assert rerun.failures == 0
    assert _count(clean_db, "games") == 1
    assert _count(clean_db, "player_game_stats") == 8
    assert _count(clean_db, "provider_entity_map") == 11


def test_espn_ingestion_persists_venue_and_attendance_from_game_info(clean_db):
    """A real live-captured summary payload (tests/fixtures/
    espn_summary_with_game_info.json, curled from event 401736393 on
    2026-07-09) has ESPN's gameInfo block -- venue_name/attendance must
    land on the games row end to end.
    """
    result = sync_date(clean_db, FakeEspnClientWithGameInfo(), date(2025, 7, 6))
    assert result.failures == 0
    assert result.box_scores_ingested == 1

    with clean_db.connection() as conn:
        venue = conn.execute("SELECT venue_name, attendance FROM games").fetchone()
        assert venue == ("Mohegan Sun Arena", 7508)

    # Re-ingestion keeps the same real values (update-on-change, not a
    # blind overwrite -- see entity_repo.update_game_venue_info).
    rerun = sync_date(clean_db, FakeEspnClientWithGameInfo(), date(2025, 7, 6))
    assert rerun.failures == 0
    with clean_db.connection() as conn:
        venue = conn.execute("SELECT venue_name, attendance FROM games").fetchone()
        assert venue == ("Mohegan Sun Arena", 7508)


def test_espn_ingestion_persists_officials_from_game_info(clean_db):
    """The same real live-captured summary payload (tests/fixtures/
    espn_summary_with_game_info.json) also carries gameInfo.officials --
    all 3 must land in game_officials, in order, end to end.
    """
    result = sync_date(clean_db, FakeEspnClientWithGameInfo(), date(2025, 7, 6))
    assert result.failures == 0
    assert result.box_scores_ingested == 1

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT official_name, role, official_order FROM game_officials ORDER BY official_order"
        ).fetchall()
        assert rows == [
            ("Tiara Cruse", "Referee", 1),
            ("Paul Tuomey", "Referee", 2),
            ("Catherine Chang", "Referee", 3),
        ]

    # Re-ingestion is idempotent: delete-then-reinsert must land at exactly
    # 3 rows again, never accumulating duplicates.
    rerun = sync_date(clean_db, FakeEspnClientWithGameInfo(), date(2025, 7, 6))
    assert rerun.failures == 0
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM game_officials").fetchone()
        assert count == (3,)


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


class FakeKalshiPlayerPropClient:
    """A single KXWNBAREB player-prop market for a player FakeEspnClient
    seeds (Breanna Stewart, New York Liberty, external_id 2998928)."""

    def fetch_sports_series(self) -> object:
        return {"series": [{"ticker": "KXWNBAREB", "title": "WNBA Player Rebounds"}]}

    def fetch_markets_page(self, series_ticker: str, **_: object) -> object:
        return {
            "cursor": "",
            "markets": [
                {
                    "ticker": "KXWNBAREB-25JUL06NYSEA-YES",
                    "event_ticker": "KXWNBAREB-25JUL06NYSEA",
                    "title": "Breanna Stewart: 8+ rebounds",
                    "status": "active",
                    "yes_bid_dollars": "0.5500",
                    "yes_ask_dollars": "0.5700",
                    "last_price_dollars": "0.5600",
                    "volume_fp": "20.00",
                    "open_interest_fp": "5.00",
                    "liquidity_dollars": "2.00",
                    "close_time": "2025-07-06T23:00:00Z",
                }
            ],
        }


def test_kalshi_player_prop_resolves_via_player_and_team_date(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = ingest_kalshi_wnba_markets(clean_db, FakeKalshiPlayerPropClient())
    assert result.failures == 0
    assert result.snapshots_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT p.full_name, g.id FROM market_price_snapshots m "
            "JOIN players p ON p.id = m.player_id "
            "JOIN games g ON g.id = m.game_id "
            "WHERE m.market_external_id = %s",
            ("KXWNBAREB-25JUL06NYSEA-YES",),
        ).fetchone()
    assert row is not None, "expected the prop to resolve both player_id and game_id"
    assert row[0] == "Breanna Stewart"


class FakePolymarketPlayerPropClient:
    """A single player-prop market for a player FakeEspnClient seeds
    (Breanna Stewart, New York Liberty, external_id 2998928)."""

    def fetch_wnba_events_page(self, *, offset: int = 0, **_: object) -> object:
        if offset != 0:
            return []
        return [
            {
                "id": "999101",
                "markets": [
                    {
                        "id": "999102",
                        "question": "Breanna Stewart: Points O/U 20.5",
                        "bestBid": 0.5,
                        "bestAsk": 0.52,
                        "lastTradePrice": 0.51,
                        "outcomePrices": '["0.51", "0.49"]',
                        "groupItemTitle": "Over",
                        "volumeNum": 300,
                        "liquidityNum": 100,
                        "closed": False,
                        "active": True,
                        "endDateIso": "2025-07-06T23:00:00Z",
                    }
                ],
            }
        ]


def test_polymarket_player_prop_resolves_via_player_and_team_date(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = ingest_polymarket_wnba_markets(clean_db, FakePolymarketPlayerPropClient())
    assert result.snapshots_inserted == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT p.full_name, g.id FROM market_price_snapshots m "
            "JOIN players p ON p.id = m.player_id "
            "JOIN games g ON g.id = m.game_id "
            "WHERE m.market_external_id = %s",
            ("999102",),
        ).fetchone()
    assert row is not None, "expected the prop to resolve both player_id and game_id"
    assert row[0] == "Breanna Stewart"


class FakeKalshiTeamDerivativeClient:
    """A two-team total market and a single-team spread market for the
    same NY/SEA game FakeEspnClient seeds, sharing one event ticker to
    exercise the per-market (not per-event) resolution path."""

    def fetch_sports_series(self) -> object:
        return {
            "series": [
                {"ticker": "KXWNBATOTAL", "title": "WNBA Total"},
                {"ticker": "KXWNBASPREAD", "title": "WNBA Spread"},
            ]
        }

    def fetch_markets_page(self, series_ticker: str, **_: object) -> object:
        if series_ticker == "KXWNBATOTAL":
            return {
                "cursor": "",
                "markets": [
                    {
                        "ticker": "KXWNBATOTAL-25JUL06NYSEA-YES",
                        "event_ticker": "KXWNBATOTAL-25JUL06NYSEA",
                        "title": "New York vs Seattle",
                        "status": "active",
                        "yes_bid_dollars": "0.5000",
                        "yes_ask_dollars": "0.5200",
                        "last_price_dollars": "0.5100",
                        "volume_fp": "10.00",
                        "open_interest_fp": "5.00",
                        "liquidity_dollars": "1.00",
                        "close_time": "2025-07-07T00:00:00Z",
                    }
                ],
            }
        if series_ticker == "KXWNBASPREAD":
            return {
                "cursor": "",
                "markets": [
                    {
                        "ticker": "KXWNBASPREAD-25JUL06NYSEA-NY",
                        "event_ticker": "KXWNBASPREAD-25JUL06NYSEA",
                        "title": "New York wins by over 3.5 points?",
                        "status": "active",
                        "yes_bid_dollars": "0.4500",
                        "yes_ask_dollars": "0.4700",
                        "last_price_dollars": "0.4600",
                        "volume_fp": "10.00",
                        "open_interest_fp": "5.00",
                        "liquidity_dollars": "1.00",
                        "close_time": "2025-07-07T00:00:00Z",
                    }
                ],
            }
        return {"cursor": "", "markets": []}


def test_kalshi_team_derivative_markets_resolve_via_team_and_ticker_date(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = ingest_kalshi_wnba_markets(clean_db, FakeKalshiTeamDerivativeClient())
    assert result.failures == 0
    assert result.snapshots_inserted == 2

    with clean_db.connection() as conn:
        total_game = conn.execute(
            "SELECT game_id FROM market_price_snapshots WHERE market_external_id = %s",
            ("KXWNBATOTAL-25JUL06NYSEA-YES",),
        ).fetchone()
        spread_game = conn.execute(
            "SELECT game_id FROM market_price_snapshots WHERE market_external_id = %s",
            ("KXWNBASPREAD-25JUL06NYSEA-NY",),
        ).fetchone()
    assert total_game is not None and total_game[0] is not None
    assert spread_game is not None and spread_game[0] is not None
    assert total_game[0] == spread_game[0]


class FakePolymarketTeamDerivativeClient:
    """A two-team total market and a single-team spread market for the
    same NY/SEA game FakeEspnClient seeds."""

    def fetch_wnba_events_page(self, *, offset: int = 0, **_: object) -> object:
        if offset != 0:
            return []
        return [
            {
                "id": "999201",
                "markets": [
                    {
                        "id": "999202",
                        "question": "New York Liberty vs. Seattle Storm: O/U 165.5",
                        "bestBid": 0.5,
                        "bestAsk": 0.52,
                        "lastTradePrice": 0.51,
                        "outcomePrices": '["0.51", "0.49"]',
                        "groupItemTitle": "Over",
                        "volumeNum": 200,
                        "liquidityNum": 80,
                        "closed": False,
                        "active": True,
                        "endDateIso": "2025-07-06T23:00:00Z",
                    },
                    {
                        "id": "999203",
                        "question": "Spread: New York Liberty (-3.5)",
                        "bestBid": 0.45,
                        "bestAsk": 0.47,
                        "lastTradePrice": 0.46,
                        "outcomePrices": '["0.46", "0.54"]',
                        "groupItemTitle": "Yes",
                        "volumeNum": 150,
                        "liquidityNum": 60,
                        "closed": False,
                        "active": True,
                        "endDateIso": "2025-07-06T23:00:00Z",
                    },
                ],
            }
        ]


def test_polymarket_team_derivative_markets_resolve_via_team_and_close_time(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = ingest_polymarket_wnba_markets(clean_db, FakePolymarketTeamDerivativeClient())
    assert result.snapshots_inserted == 2

    with clean_db.connection() as conn:
        total_game = conn.execute(
            "SELECT game_id FROM market_price_snapshots WHERE market_external_id = %s",
            ("999202",),
        ).fetchone()
        spread_game = conn.execute(
            "SELECT game_id FROM market_price_snapshots WHERE market_external_id = %s",
            ("999203",),
        ).fetchone()
    assert total_game is not None and total_game[0] is not None
    assert spread_game is not None and spread_game[0] is not None
    assert total_game[0] == spread_game[0]


def test_find_player_by_name_falls_back_to_diacritic_insensitive_match(clean_db):
    # Real gap found live: ESPN stores "Janelle Salaun" (no diaeresis);
    # Kalshi/Polymarket prop titles spell it "Janelle Salaün".
    with clean_db.connection() as conn:
        entity_repo.resolve_or_create_player(
            conn, "espn", PlayerRef(external_id="1", full_name="Janelle Salaun", position="G")
        )
        conn.commit()

        assert entity_repo.find_player_by_name(conn, "Janelle Salaün") is not None
        assert entity_repo.find_player_by_name(conn, "Someone Else") is None


def test_resolve_or_create_player_by_name_backfills_bio_on_name_match(clean_db):
    # An ESPN-only player has no bio data (ESPN box scores never carry
    # height/weight/jersey_number/college/age). The first time a
    # balldontlie row names the SAME player, resolve_or_create_player_by_name
    # must join onto that existing row by name AND backfill the bio
    # columns in place, not just return the id untouched.
    with clean_db.connection() as conn:
        espn_id = entity_repo.resolve_or_create_player(
            conn, "espn", PlayerRef(external_id="1068", full_name="Nneka Ogwumike", position="F")
        )
        conn.commit()

        bdl_id = entity_repo.resolve_or_create_player_by_name(
            conn,
            "balldontlie",
            "777",
            "Nneka Ogwumike",
            "F",
            "6' 2\"",
            "173 lbs",
            "30",
            "Stanford",
            34,
        )
        conn.commit()
        assert bdl_id == espn_id

        row = conn.execute(
            "SELECT height, weight, jersey_number, college, age FROM players WHERE id = %s",
            (espn_id,),
        ).fetchone()
        assert row == ("6' 2\"", "173 lbs", "30", "Stanford", 34)


def test_resolve_or_create_player_by_name_updates_bio_on_repeat_crosswalk_hit(clean_db):
    # Bio data is a snapshot that legitimately drifts (trade -> new jersey
    # number, birthday -> new age). A player already mapped via the
    # provider_entity_map crosswalk (not just matched by name) must also
    # get bio updates on a later ingestion run, not just on first contact.
    with clean_db.connection() as conn:
        player_id = entity_repo.resolve_or_create_player_by_name(
            conn,
            "balldontlie",
            "777",
            "Nneka Ogwumike",
            "F",
            "6' 2\"",
            "173 lbs",
            "30",
            "Stanford",
            34,
        )
        conn.commit()

        again = entity_repo.resolve_or_create_player_by_name(
            conn,
            "balldontlie",
            "777",
            "Nneka Ogwumike",
            "F",
            "6' 2\"",
            "173 lbs",
            "3",
            "Stanford",
            35,
        )
        conn.commit()
        assert again == player_id

        row = conn.execute(
            "SELECT jersey_number, age FROM players WHERE id = %s", (player_id,)
        ).fetchone()
        assert row == ("3", 35)


def test_resolve_or_create_player_by_name_inserts_bio_on_create(clean_db):
    with clean_db.connection() as conn:
        player_id = entity_repo.resolve_or_create_player_by_name(
            conn,
            "balldontlie",
            "888",
            "Brand New Player",
            "G",
            "5' 9\"",
            "140 lbs",
            "0",
            "Texas",
            22,
        )
        conn.commit()

        row = conn.execute(
            "SELECT full_name, position, height, weight, jersey_number, college, age "
            "FROM players WHERE id = %s",
            (player_id,),
        ).fetchone()
        assert row == ("Brand New Player", "G", "5' 9\"", "140 lbs", "0", "Texas", 22)


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
            '<script>window[\'__espnfitt__\']={"page": {"content": {"injuries": ['
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
            '<script>window[\'__espnfitt__\']={"page": {"content": {"injuries": ['
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
    result = backfill_injury_history(clean_db, fake_client, date(2024, 4, 25), date(2024, 4, 25))
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


class FakeBalldontlieTeamAdvancedStatsClient:
    """One game matching the ESPN fixture's NY vs SEA, 2025-07-06 game, and
    two team-advanced-stats rows (one per team) -- stats values are the
    REAL payload captured live from /wnba/v1/team_game_advanced_stats
    (tests/fixtures/balldontlie_team_advanced_stats.json, Washington
    Mystics row), with team/game identifiers substituted so the row
    resolves onto the SAME canonical game+teams ESPN's box score already
    created (proving the crosswalk, same technique as
    FakeBalldontlieClient above)."""

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

    def fetch_team_advanced_stats_page(
        self, season: int, *, cursor: int | None = None, per_page: int = 100
    ):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "id": 600001,
                    "team": {"id": 1, "abbreviation": "NY"},
                    "game": {"id": 9001, "date": "2025-07-06T17:00:00.000Z", "season": 2025},
                    "period": 0,
                    "stats": {
                        "misc": {"blocks": 4, "points_paint": 36},
                        "usage": {"usage_percentage": 1},
                        "scoring": {"percentage_points2pt": 0.468},
                        "advanced": {
                            "minutes": "200:00",
                            "offensive_rating": 119,
                            "defensive_rating": 113.9,
                            "net_rating": 5.1,
                            "pace": 94.8,
                            "possessions": 79,
                            "true_shooting_percentage": 0.63,
                            "effective_field_goal_percentage": 0.582,
                            "usage_percentage": 1,
                            "assist_percentage": 0.581,
                            "assist_ratio": 17,
                            "assist_to_turnover": 2,
                            "turnover_ratio": 11.4,
                            "rebound_percentage": 0.422,
                            "offensive_rebound_percentage": 0.273,
                            "defensive_rebound_percentage": 0.52,
                            "pie": 0.558,
                        },
                        "four_factors": {
                            "free_throw_attempt_rate": 0.508,
                            "team_turnover_percentage": 0.114,
                            "opp_effective_field_goal_percentage": 0.486,
                            "opp_free_throw_attempt_rate": 0.365,
                            "opp_team_turnover_percentage": 0.203,
                            "opp_offensive_rebound_percentage": 0.48,
                        },
                    },
                },
                {
                    "id": 600002,
                    "team": {"id": 2, "abbreviation": "SEA"},
                    "game": {"id": 9001, "date": "2025-07-06T17:00:00.000Z", "season": 2025},
                    "period": 0,
                    "stats": {
                        "misc": {"blocks": 2, "points_paint": 34},
                        "usage": {"usage_percentage": 1},
                        "scoring": {"percentage_points2pt": 0.4},
                        "advanced": {
                            "minutes": "200:00",
                            "offensive_rating": 113.9,
                            "defensive_rating": 119,
                            "net_rating": -5.1,
                            "pace": 94.8,
                            "possessions": 79,
                            "true_shooting_percentage": 0.524,
                            "effective_field_goal_percentage": 0.486,
                            "usage_percentage": 1,
                            "assist_percentage": 0.8,
                            "assist_ratio": 18.9,
                            "assist_to_turnover": 1.5,
                            "turnover_ratio": 20.3,
                            "rebound_percentage": 0.578,
                            "offensive_rebound_percentage": 0.48,
                            "defensive_rebound_percentage": 0.727,
                            "pie": 0.442,
                        },
                        "four_factors": {
                            "free_throw_attempt_rate": 0.365,
                            "team_turnover_percentage": 0.203,
                            "opp_effective_field_goal_percentage": 0.582,
                            "opp_free_throw_attempt_rate": 0.508,
                            "opp_team_turnover_percentage": 0.114,
                            "opp_offensive_rebound_percentage": 0.273,
                        },
                    },
                },
            ],
            "meta": {"next_cursor": None, "per_page": 2},
        }


def test_balldontlie_team_advanced_stats_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA

    result = backfill_team_advanced_stats_season(
        clean_db, FakeBalldontlieTeamAdvancedStatsClient(), 2025
    )
    assert result.games_seen == 1
    assert result.games_resolved == 1
    assert result.games_unresolved == 0
    assert result.stat_rows_seen == 2
    assert result.stat_rows_inserted == 2
    assert result.unresolved_games_for_stats == 0
    assert result.unresolved_teams_for_stats == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT t.abbreviation, tas.offensive_rating, tas.true_shooting_percentage, "
            "tas.pie, tas.misc_stats "
            "FROM team_advanced_stats tas "
            "JOIN teams t ON t.id = tas.team_id "
            "WHERE tas.source = 'balldontlie' ORDER BY t.abbreviation"
        ).fetchall()
    assert len(rows) == 2
    ny, sea = rows
    assert ny[0] == "NY"
    assert float(ny[1]) == pytest.approx(119)
    assert float(ny[2]) == pytest.approx(0.63)
    assert float(ny[3]) == pytest.approx(0.558)
    assert ny[4] == {"blocks": 4, "points_paint": 36}
    assert sea[0] == "SEA"
    assert float(sea[1]) == pytest.approx(113.9)

    # Crosswalk correctness: balldontlie's team abbreviation resolves via
    # find_team_by_abbreviation onto the SAME canonical teams row ESPN's
    # box score already created for this game -- team_advanced_stats has
    # exactly the 2 teams from that one game, no forked duplicate identity.
    with clean_db.connection() as conn:
        team_count = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
    assert team_count == 2

    # Upserted, not append-only: re-running updates the same rows.
    rerun = backfill_team_advanced_stats_season(
        clean_db, FakeBalldontlieTeamAdvancedStatsClient(), 2025
    )
    assert rerun.stat_rows_inserted == 2
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM team_advanced_stats WHERE source = 'balldontlie'"
        ).fetchone()[0]
    assert count == 2


class FakeBalldontlieStandingsClient:
    """Two standings rows -- real field shapes captured live from
    /wnba/v1/standings (tests/fixtures/balldontlie_standings.json's NY
    Liberty and Seattle Storm rows) -- for the same teams FakeEspnClient's
    NY vs SEA game seeds, so each row resolves onto the SAME canonical
    teams ESPN's box score already created. `ny_wins` is overridable to
    exercise that a re-fetch genuinely changes standings values (unlike
    per-game stats, which are immutable once a game is final)."""

    def __init__(self, ny_wins: int = 27) -> None:
        self._ny_wins = ny_wins

    def fetch_standings(self, season: int) -> object:
        assert season == 2025
        return {
            "data": [
                {
                    "team": {
                        "id": 1,
                        "conference": "Eastern Conference",
                        "city": "New York",
                        "name": "Liberty",
                        "full_name": "New York Liberty",
                        "abbreviation": "NY",
                    },
                    "season": 2025,
                    "conference": "Eastern Conference",
                    "wins": self._ny_wins,
                    "losses": 17,
                    "win_percentage": 0.614,
                    "games_behind": 3,
                    "home_record": "17-5",
                    "away_record": "10-12",
                    "conference_record": "15-5",
                    "playoff_seed": 2,
                },
                {
                    "team": {
                        "id": 2,
                        "conference": "Western Conference",
                        "city": "Seattle",
                        "name": "Storm",
                        "full_name": "Seattle Storm",
                        "abbreviation": "SEA",
                    },
                    "season": 2025,
                    "conference": "Western Conference",
                    "wins": 23,
                    "losses": 21,
                    "win_percentage": 0.523,
                    "games_behind": 11,
                    "home_record": "10-12",
                    "away_record": "13-9",
                    "conference_record": "12-12",
                    "playoff_seed": 4,
                },
            ]
        }


def test_balldontlie_standings_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA

    result = backfill_standings_season(clean_db, FakeBalldontlieStandingsClient(), 2025)
    assert result.rows_seen == 2
    assert result.rows_inserted == 2
    assert result.unresolved_teams == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT t.abbreviation, ts.wins, ts.losses, ts.win_percentage, "
            "ts.games_behind, ts.home_record, ts.playoff_seed "
            "FROM team_standings ts JOIN teams t ON t.id = ts.team_id "
            "WHERE ts.source = 'balldontlie' ORDER BY t.abbreviation"
        ).fetchall()
    assert len(rows) == 2
    ny, sea = rows
    assert ny[0] == "NY"
    assert ny[1] == 27
    assert ny[2] == 17
    assert float(ny[3]) == pytest.approx(0.614)
    assert float(ny[4]) == pytest.approx(3)
    assert ny[5] == "17-5"
    assert ny[6] == 2
    assert sea[0] == "SEA"
    assert sea[1] == 23

    # Crosswalk correctness: balldontlie's team abbreviation resolves onto
    # the SAME canonical teams rows ESPN's box score already created -- no
    # forked duplicate identity.
    with clean_db.connection() as conn:
        team_count = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
    assert team_count == 2

    # Upserted, not append-only, and this matters more here than for the
    # per-game stats tables: standings genuinely change on every re-fetch
    # (wins increments as the season progresses), so a re-run must both
    # avoid duplicating rows AND overwrite the changed values.
    rerun = backfill_standings_season(clean_db, FakeBalldontlieStandingsClient(ny_wins=28), 2025)
    assert rerun.rows_inserted == 2
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM team_standings WHERE source = 'balldontlie'"
        ).fetchone()[0]
        ny_wins = conn.execute(
            "SELECT ts.wins FROM team_standings ts JOIN teams t ON t.id = ts.team_id "
            "WHERE t.abbreviation = 'NY'"
        ).fetchone()[0]
    assert count == 2
    assert ny_wins == 28


class FakeBalldontlieStandingsUnresolvedTeamClient:
    """One resolvable row (NY, matching FakeEspnClient's seeded team) and
    one row for a team never seeded in this test's DB, to exercise the
    unresolved-team skip path."""

    def fetch_standings(self, season: int) -> object:
        del season
        return {
            "data": [
                {
                    "team": {"id": 1, "abbreviation": "NY"},
                    "season": 2025,
                    "conference": "Eastern Conference",
                    "wins": 27,
                    "losses": 17,
                    "win_percentage": 0.614,
                    "games_behind": 3,
                    "home_record": "17-5",
                    "away_record": "10-12",
                    "conference_record": "15-5",
                    "playoff_seed": 2,
                },
                {
                    "team": {"id": 99, "abbreviation": "ZZZ"},
                    "season": 2025,
                    "conference": "Western Conference",
                    "wins": 1,
                    "losses": 1,
                    "win_percentage": 0.5,
                    "games_behind": 0,
                    "home_record": "1-0",
                    "away_record": "0-1",
                    "conference_record": "1-1",
                    "playoff_seed": 7,
                },
            ]
        }


def test_balldontlie_standings_backfill_skips_unresolved_team(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA

    result = backfill_standings_season(
        clean_db, FakeBalldontlieStandingsUnresolvedTeamClient(), 2025
    )
    assert result.rows_seen == 2
    assert result.rows_inserted == 1
    assert result.unresolved_teams == 1

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM team_standings").fetchone()[0]
    assert count == 1


def test_balldontlie_standings_backfill_writes_history_and_dedups_unchanged_rerun(clean_db):
    """team_standings_history is append-only, but a re-run with IDENTICAL
    values must not accumulate meaningless duplicate rows -- unlike
    team_standings (always upserted regardless), a no-op history insert is
    skipped."""
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA

    result = backfill_standings_season(clean_db, FakeBalldontlieStandingsClient(), 2025)
    assert result.history_rows_inserted == 2
    assert result.history_rows_skipped_no_change == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT t.abbreviation, h.wins, h.losses, h.captured_at "
            "FROM team_standings_history h JOIN teams t ON t.id = h.team_id "
            "WHERE h.source = 'balldontlie' ORDER BY t.abbreviation"
        ).fetchall()
    assert len(rows) == 2
    ny, sea = rows
    assert ny[0] == "NY"
    assert ny[1] == 27
    assert ny[2] == 17
    assert ny[3] is not None
    assert sea[0] == "SEA"
    assert sea[1] == 23

    # Current-state team_standings still has exactly one row per team.
    with clean_db.connection() as conn:
        current_count = conn.execute(
            "SELECT count(*) FROM team_standings WHERE source = 'balldontlie'"
        ).fetchone()[0]
    assert current_count == 2

    # Re-run with the SAME (unchanged) values: no new history rows.
    rerun = backfill_standings_season(clean_db, FakeBalldontlieStandingsClient(), 2025)
    assert rerun.history_rows_inserted == 0
    assert rerun.history_rows_skipped_no_change == 2

    with clean_db.connection() as conn:
        history_count = conn.execute(
            "SELECT count(*) FROM team_standings_history WHERE source = 'balldontlie'"
        ).fetchone()[0]
    assert history_count == 2


def test_balldontlie_standings_backfill_appends_new_history_row_on_change(clean_db):
    """When a team's standings genuinely change between runs, a NEW history
    row is appended (old row is kept, not overwritten) while the unchanged
    team's history is skipped as a no-op."""
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA

    backfill_standings_season(clean_db, FakeBalldontlieStandingsClient(ny_wins=27), 2025)
    rerun = backfill_standings_season(clean_db, FakeBalldontlieStandingsClient(ny_wins=28), 2025)

    # NY changed (27 -> 28 wins): new history row. SEA unchanged: skipped.
    assert rerun.history_rows_inserted == 1
    assert rerun.history_rows_skipped_no_change == 1

    with clean_db.connection() as conn:
        ny_history = conn.execute(
            "SELECT h.wins, h.captured_at FROM team_standings_history h "
            "JOIN teams t ON t.id = h.team_id "
            "WHERE t.abbreviation = 'NY' ORDER BY h.captured_at ASC"
        ).fetchall()
        total_history = conn.execute("SELECT count(*) FROM team_standings_history").fetchone()[0]

    assert total_history == 3  # 2 from first run + 1 new NY row from the rerun
    assert len(ny_history) == 2
    assert ny_history[0][0] == 27
    assert ny_history[1][0] == 28
    # Distinct, real captured_at timestamps -- proves it's a time series,
    # not an overwrite.
    assert ny_history[0][1] != ny_history[1][1]

    # team_standings (current-state) still has exactly one row per team,
    # holding the LATEST value.
    with clean_db.connection() as conn:
        current_ny_wins = conn.execute(
            "SELECT ts.wins FROM team_standings ts JOIN teams t ON t.id = ts.team_id "
            "WHERE t.abbreviation = 'NY' AND ts.source = 'balldontlie'"
        ).fetchone()[0]
    assert current_ny_wins == 28


class FakeBalldontliePlaysClient:
    """Same NY vs SEA 2025-07-06 game as FakeBalldontlieClient, plus two
    plays for that game -- one per team, to prove both resolve."""

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

    def fetch_plays(self, game_id: int):
        assert game_id == 9001
        return {
            "data": [
                {
                    "game_id": 9001,
                    "order": 1,
                    "type": "Jumpball",
                    "text": "Test jumpball",
                    "home_score": 0,
                    "away_score": 0,
                    "period": 1,
                    "clock": "10:00",
                    "scoring_play": False,
                    "score_value": 0,
                    "team": {"id": 2, "abbreviation": "SEA"},
                },
                {
                    "game_id": 9001,
                    "order": 2,
                    "type": "Jump Shot",
                    "text": "Nneka Ogwumike makes 15-foot jumper",
                    "home_score": 2,
                    "away_score": 0,
                    "period": 1,
                    "clock": "9:50",
                    "scoring_play": True,
                    "score_value": 2,
                    "team": {"id": 1, "abbreviation": "NY"},
                },
            ]
        }


def test_balldontlie_plays_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = backfill_season_plays(clean_db, FakeBalldontliePlaysClient(), 2025)
    assert result.games_seen == 1
    assert result.games_resolved == 1
    assert result.games_unresolved == 0
    assert result.plays_seen == 2
    assert result.plays_inserted == 2
    assert result.games_with_unresolved_teams == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT gp.sequence, gp.play_type, gp.scoring_play, t.abbreviation "
            "FROM game_plays gp JOIN teams t ON t.id = gp.team_id "
            "ORDER BY gp.sequence"
        ).fetchall()
    assert rows == [
        (1, "Jumpball", False, "SEA"),
        (2, "Jump Shot", True, "NY"),
    ]

    # Idempotent, not duplicated: re-running the same season doesn't add
    # more rows for a game already ingested.
    rerun = backfill_season_plays(clean_db, FakeBalldontliePlaysClient(), 2025)
    assert rerun.plays_seen == 2
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM game_plays").fetchone()[0]
    assert count == 2


class FakeBalldontlieShotZoneClient:
    """One player row (Nneka Ogwumike, ESPN external_id '1068') and one
    team row (Seattle Storm), matching FakeEspnClient's seeded entities."""

    _ZONES = {
        "restricted_area": {"fga": 10, "fgm": 6},
        "in_the_paint_non_ra": {"fga": 5, "fgm": 2},
        "mid_range": {"fga": 8, "fgm": 3},
        "left_corner_3": {"fga": 1, "fgm": 0},
        "right_corner_3": {"fga": 2, "fgm": 1},
        "corner_3": {"fga": 3, "fgm": 1},
        "above_the_break_3": {"fga": 4, "fgm": 1},
        "backcourt": {"fga": 0, "fgm": 0},
    }

    def fetch_player_shot_zone_stats_page(
        self, season: int, *, cursor: int | None = None, per_page: int = 100
    ):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "id": 1,
                    "player": {
                        "id": 777,
                        "first_name": "Nneka",
                        "last_name": "Ogwumike",
                        "position": "F",
                    },
                    "team": {"id": 2, "abbreviation": "SEA"},
                    "season": 2025,
                    "season_type": "regular",
                    "stats": {"shot_zones": self._ZONES},
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }

    def fetch_team_shot_zone_stats_page(
        self, season: int, *, cursor: int | None = None, per_page: int = 100
    ):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "id": 2,
                    "team": {"id": 2, "abbreviation": "SEA"},
                    "season": 2025,
                    "season_type": "regular",
                    "stats": {"shot_zones": self._ZONES},
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }


def test_balldontlie_shot_zone_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, incl. Ogwumike

    result = backfill_season_shot_zones(clean_db, FakeBalldontlieShotZoneClient(), 2025)
    assert result.player_rows_seen == 1
    assert result.player_rows_inserted == 1
    assert result.team_rows_seen == 1
    assert result.team_rows_inserted == 1
    assert result.unresolved_teams == 0

    with clean_db.connection() as conn:
        player_row = conn.execute(
            "SELECT p.full_name, pz.restricted_area_fga, pz.restricted_area_fgm, "
            "pz.mid_range_fga, t.abbreviation "
            "FROM player_shot_zone_stats pz "
            "JOIN players p ON p.id = pz.player_id "
            "JOIN teams t ON t.id = pz.team_id "
            "WHERE pz.source = 'balldontlie'"
        ).fetchone()
        team_row = conn.execute(
            "SELECT t.abbreviation, tz.restricted_area_fga, tz.backcourt_fgm "
            "FROM team_shot_zone_stats tz JOIN teams t ON t.id = tz.team_id "
            "WHERE tz.source = 'balldontlie'"
        ).fetchone()

    assert player_row == ("Nneka Ogwumike", 10, 6, 8, "SEA")
    assert team_row == ("SEA", 10, 0)

    # Crosswalk correctness: balldontlie's player id resolves to the SAME
    # canonical player ESPN's box score already created.
    with clean_db.connection() as conn:
        espn_player_id = entity_repo.lookup_internal_id(conn, "espn", "player", "1068")
        bdl_player_id = entity_repo.lookup_internal_id(conn, "balldontlie", "player", "777")
    assert espn_player_id is not None
    assert bdl_player_id == espn_player_id

    # Upserted, not append-only: re-running updates the same rows.
    rerun = backfill_season_shot_zones(clean_db, FakeBalldontlieShotZoneClient(), 2025)
    assert rerun.player_rows_inserted == 1
    assert rerun.team_rows_inserted == 1
    with clean_db.connection() as conn:
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM player_shot_zone_stats), "
            "(SELECT count(*) FROM team_shot_zone_stats)"
        ).fetchone()
    assert counts == (1, 1)


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


class FakeBalldontlieOddsClient:
    """One game matching FakeEspnClient's NY vs SEA, 2025-07-06 game
    (external id 9001, same technique as FakeBalldontlieClient above), and
    two game-odds rows for that game -- REAL field shapes captured live
    from /wnba/v1/odds (tests/fixtures/balldontlie_odds.json's draftkings/
    fanatics rows for game 24909), with game_id substituted to 9001 so both
    resolve onto the SAME canonical game ESPN's box score already
    created."""

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

    def fetch_odds_page(self, day: date, *, cursor: int | None = None, per_page: int = 100):
        del cursor, per_page
        if day != date(2025, 7, 6):
            return {"data": [], "meta": {"per_page": 0}}
        return {
            "data": [
                {
                    "id": 266605323,
                    "game_id": 9001,
                    "vendor": "draftkings",
                    "spread_home_value": "8.5",
                    "spread_home_odds": 105,
                    "spread_away_value": "-8.5",
                    "spread_away_odds": -135,
                    "moneyline_home_odds": 900,
                    "moneyline_away_odds": -1850,
                    "total_value": "166.5",
                    "total_over_odds": -110,
                    "total_under_odds": -120,
                    "updated_at": "2026-07-08T01:59:02.636Z",
                },
                {
                    "id": 266605328,
                    "game_id": 9001,
                    "vendor": "fanatics",
                    "spread_home_value": "9.5",
                    "spread_home_odds": 105,
                    "spread_away_value": "-9.5",
                    "spread_away_odds": -140,
                    "moneyline_home_odds": 4000,
                    "moneyline_away_odds": -20000,
                    "total_value": "166.5",
                    "total_over_odds": -105,
                    "total_under_odds": -125,
                    "updated_at": "2026-07-08T02:01:02.331Z",
                },
            ],
            "meta": {"next_cursor": None, "per_page": 2},
        }


def test_balldontlie_odds_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, 2025-07-06

    result = backfill_odds_date_range(
        clean_db, FakeBalldontlieOddsClient(), date(2025, 7, 6), date(2025, 7, 6)
    )
    assert result.dates_processed == 1
    assert result.rows_seen == 2
    assert result.rows_inserted == 2
    assert result.unresolved_games == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT vendor, moneyline_home_odds, spread_home_value, total_value "
            "FROM sportsbook_game_odds ORDER BY vendor"
        ).fetchall()
    assert len(rows) == 2
    draftkings = next(r for r in rows if r[0] == "draftkings")
    assert draftkings[1] == 900
    assert float(draftkings[2]) == pytest.approx(8.5)
    assert float(draftkings[3]) == pytest.approx(166.5)

    # Append-only but idempotent: UNIQUE(external_id, captured_at) makes a
    # re-run over an unchanged window a no-op, not a duplicate.
    rerun = backfill_odds_date_range(
        clean_db, FakeBalldontlieOddsClient(), date(2025, 7, 6), date(2025, 7, 6)
    )
    assert rerun.rows_inserted == 0
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM sportsbook_game_odds").fetchone()[0]
    assert count == 2


class FakeBalldontlieOddsUnresolvedGameClient:
    """No games at all in the season (so game_id 9999 below can never
    resolve) -- exercises the unresolved-game skip path."""

    def fetch_games_page(self, season: int, *, cursor: int | None = None, per_page: int = 100):
        del season, cursor, per_page
        return {"data": [], "meta": {"next_cursor": None, "per_page": 0}}

    def fetch_odds_page(self, day: date, *, cursor: int | None = None, per_page: int = 100):
        del cursor, per_page
        if day != date(2025, 7, 6):
            return {"data": [], "meta": {"per_page": 0}}
        return {
            "data": [
                {
                    "id": 1,
                    "game_id": 9999,
                    "vendor": "draftkings",
                    "spread_home_value": "1.5",
                    "spread_home_odds": -110,
                    "spread_away_value": "-1.5",
                    "spread_away_odds": -110,
                    "moneyline_home_odds": 150,
                    "moneyline_away_odds": -180,
                    "total_value": "160.5",
                    "total_over_odds": -110,
                    "total_under_odds": -110,
                    "updated_at": "2026-07-08T01:59:02.636Z",
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }


def test_balldontlie_odds_backfill_skips_unresolved_game(clean_db):
    result = backfill_odds_date_range(
        clean_db, FakeBalldontlieOddsUnresolvedGameClient(), date(2025, 7, 6), date(2025, 7, 6)
    )
    assert result.rows_seen == 1
    assert result.rows_inserted == 0
    assert result.unresolved_games == 1
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM sportsbook_game_odds").fetchone()[0]
    assert count == 0


class FakeBalldontliePlayerPropOddsClient:
    """One game (external id 9001, matching FakeEspnClient's NY vs SEA
    game) and two prop-odds rows -- one for Nneka Ogwumike (balldontlie
    player_id 777, pre-seeded via resolve_or_create_player_by_name, same
    technique as the advanced-stats/shot-zone tests above) and one for a
    never-before-seen player_id, to exercise the unresolved-player skip
    path in the same run. Field shapes are the REAL payload captured live
    (tests/fixtures/balldontlie_player_prop_odds.json), with game_id/
    player_id substituted to resolve onto seeded entities."""

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

    def fetch_player_prop_odds_page(
        self, game_id: int, *, cursor: int | None = None, per_page: int = 100
    ):
        del cursor, per_page
        assert game_id == 9001
        return {
            "data": [
                {
                    "id": 8663418827,
                    "game_id": 9001,
                    "player_id": 777,
                    "vendor": "betrivers",
                    "prop_type": "assists",
                    "line_value": "3.5",
                    "market": {"type": "milestone", "odds": 107},
                    "updated_at": "2026-07-08T00:17:10.667Z",
                },
                {
                    "id": 8663552235,
                    "game_id": 9001,
                    "player_id": 999999,
                    "vendor": "draftkings",
                    "prop_type": "assists",
                    "line_value": "10.5",
                    "market": {"type": "over_under", "over_odds": 115, "under_odds": -160},
                    "updated_at": "2026-07-08T02:17:06.821Z",
                },
            ],
            "meta": {"next_cursor": None, "per_page": 2},
        }


def test_balldontlie_player_prop_odds_backfill_end_to_end(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds NY vs SEA, incl. teams

    with clean_db.connection() as conn:
        entity_repo.resolve_or_create_player_by_name(
            conn, "balldontlie", "777", "Nneka Ogwumike", "F", None, None, None, None, None
        )
        conn.commit()

    result = backfill_player_prop_odds_season(clean_db, FakeBalldontliePlayerPropOddsClient(), 2025)
    assert result.games_seen == 1
    assert result.games_resolved == 1
    assert result.games_unresolved == 0
    assert result.prop_rows_seen == 2
    assert result.prop_rows_inserted == 1
    assert result.unresolved_players == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT p.full_name, spo.market_type, spo.odds, spo.line_value, spo.vendor "
            "FROM sportsbook_player_prop_odds spo JOIN players p ON p.id = spo.player_id"
        ).fetchone()
    assert row[0] == "Nneka Ogwumike"
    assert row[1] == "milestone"
    assert row[2] == 107
    assert float(row[3]) == pytest.approx(3.5)
    assert row[4] == "betrivers"

    # Append-only but idempotent re-run, same as game-level odds.
    rerun = backfill_player_prop_odds_season(clean_db, FakeBalldontliePlayerPropOddsClient(), 2025)
    assert rerun.prop_rows_inserted == 0
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM sportsbook_player_prop_odds").fetchone()[0]
    assert count == 1
