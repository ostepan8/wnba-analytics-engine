"""End-to-end integration tests: the-odds-api pipelines -> real Postgres.

Requires a reachable *test* Postgres database (docker compose up -d
provisions one — see db/init/001-create-test-db.sql). Skips gracefully when
unavailable. Network calls are replayed from fixtures (tests/fixtures/
odds_api_*.json, trimmed from real live-captured payloads — see
tests/unit/odds_api/test_odds_parser.py and test_scores_parser.py for
provenance) via fake clients so results are deterministic.

Games are seeded directly via entity_repo (not through FakeEspnClient's own
fixture, which covers different teams/dates) so team names and timestamps
line up exactly with the odds_api_* fixtures.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from wnba_engine.models.games import GameStatus, ScoreboardGame, SeasonType, TeamRef
from wnba_engine.pipeline.odds_api_ingest import backfill_history, snapshot_current_odds
from wnba_engine.pipeline.odds_api_scores_ingest import snapshot_current_scores
from wnba_engine.repositories import entity_repo
from wnba_engine.validation.consistency_checks import check_odds_api_score_matches_game_score

pytestmark = pytest.mark.integration

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())


def _seed_game(
    conn,
    *,
    external_id: str,
    home_name: str,
    away_name: str,
    start_time: datetime,
    home_score: int | None = None,
    away_score: int | None = None,
    status: GameStatus = GameStatus.SCHEDULED,
) -> int:
    home_ref = TeamRef(
        external_id=f"{external_id}-home", name=home_name, abbreviation=home_name[:3].upper()
    )
    away_ref = TeamRef(
        external_id=f"{external_id}-away", name=away_name, abbreviation=away_name[:3].upper()
    )
    home_id = entity_repo.resolve_or_create_team(conn, "espn", home_ref)
    away_id = entity_repo.resolve_or_create_team(conn, "espn", away_ref)
    return entity_repo.upsert_game(
        conn,
        "espn",
        ScoreboardGame(
            external_id=external_id,
            start_time=start_time,
            season=start_time.year,
            season_type=SeasonType.REGULAR_SEASON,
            status=status,
            home_team=home_ref,
            away_team=away_ref,
            home_score=home_score,
            away_score=away_score,
        ),
        home_team_id=home_id,
        away_team_id=away_id,
    )


class FakeOddsApiCurrentOddsClient:
    def fetch_current_odds(self) -> object:
        return load_fixture("odds_api_current_odds.json")


def test_snapshot_current_odds_end_to_end(clean_db):
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-oa-1",
            home_name="Atlanta Dream",
            away_name="Seattle Storm",
            start_time=datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC),
        )
        _seed_game(
            conn,
            external_id="espn-oa-2",
            home_name="Portland Fire",
            away_name="Las Vegas Aces",
            start_time=datetime(2026, 7, 10, 2, 0, 0, tzinfo=UTC),
        )
        conn.commit()

    result = snapshot_current_odds(clean_db, FakeOddsApiCurrentOddsClient())
    assert result.events_seen == 2
    assert result.rows_seen == 4  # 2 events x 2 bookmakers each
    assert result.rows_inserted == 4
    assert result.unresolved_events == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT vendor, moneyline_home_odds, spread_home_value, total_value "
            "FROM sportsbook_game_odds WHERE source = 'the_odds_api' ORDER BY vendor"
        ).fetchall()
    assert len(rows) == 4
    fanduel_rows = [r for r in rows if r[0] == "fanduel"]
    assert len(fanduel_rows) == 2

    # Second-sight crosswalk hit: the event id is already mapped, so
    # resolution goes through lookup_internal_id, not team+date matching
    # again -- and the run is idempotent (unchanged last_update -> no-op).
    rerun = snapshot_current_odds(clean_db, FakeOddsApiCurrentOddsClient())
    assert rerun.events_seen == 2
    assert rerun.rows_inserted == 0
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM sportsbook_game_odds WHERE source = 'the_odds_api'"
        ).fetchone()[0]
    assert count == 4


def test_snapshot_current_odds_skips_unresolved_event(clean_db):
    # No games seeded at all -- neither event in the fixture can resolve.
    result = snapshot_current_odds(clean_db, FakeOddsApiCurrentOddsClient())
    assert result.events_seen == 2
    assert result.unresolved_events == 2
    assert result.rows_inserted == 0
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM sportsbook_game_odds WHERE source = 'the_odds_api'"
        ).fetchone()[0]
    assert count == 0


class FakeOddsApiHistoricalClient:
    """Always replays the SAME real historical fixture (Minnesota Lynx vs
    Connecticut Sun, 2023-06-02) regardless of the requested checkpoint
    date -- deliberately, so a backfill_history run exercises the
    idempotent-across-checkpoints path (identical captured_at each call)."""

    def __init__(self) -> None:
        self.requested_dates: list[datetime] = []

    def fetch_historical_odds(self, at: datetime) -> object:
        self.requested_dates.append(at)
        return load_fixture("odds_api_historical_odds.json")


def test_backfill_history_end_to_end(clean_db):
    game_start = datetime(2023, 6, 2, 0, 0, 0, tzinfo=UTC)
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-oa-hist-1",
            home_name="Minnesota Lynx",
            away_name="Connecticut Sun",
            start_time=game_start,
            home_score=90,
            away_score=89,
            status=GameStatus.FINAL,
        )
        conn.commit()

    client = FakeOddsApiHistoricalClient()
    result = backfill_history(clean_db, client, date(2023, 6, 1), date(2023, 6, 3))

    assert result.games_checked == 1
    assert result.checkpoints_queried == 4  # T-7d, T-24h, T-1h, closing
    assert result.checkpoints_skipped_future == 0
    assert len(client.requested_dates) == 4

    # Every checkpoint call returns the identical fixture (2 bookmaker
    # rows), so rows_seen accumulates across all 4 checkpoints but only the
    # first checkpoint's rows actually insert -- the rest are no-ops under
    # UNIQUE(external_id, captured_at).
    assert result.rows_seen == 4 * 2
    assert result.rows_inserted == 2

    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM sportsbook_game_odds WHERE source = 'the_odds_api'"
        ).fetchone()[0]
    assert count == 2


def test_backfill_history_rejects_inverted_range(clean_db):
    with pytest.raises(ValueError, match="since must not be after until"):
        backfill_history(
            clean_db, FakeOddsApiHistoricalClient(), date(2023, 6, 3), date(2023, 6, 1)
        )


class FakeOddsApiHistoricalClientWithExtraEvent:
    """Same real Lynx/Sun event as FakeOddsApiHistoricalClient, plus a
    SECOND event (same real bookmaker odds shape, team names/id/
    commence_time swapped) far outside the backfill's requested date
    range -- exercises the "don't blindly ingest everything a historical
    call happens to return" filter in backfill_history."""

    def fetch_historical_odds(self, at: datetime) -> object:
        payload = load_fixture("odds_api_historical_odds.json")
        out_of_range_event = copy.deepcopy(payload["data"][0])
        out_of_range_event["id"] = "outofrange0000000000000000000000"
        out_of_range_event["home_team"] = "Chicago Sky"
        out_of_range_event["away_team"] = "Indiana Fever"
        out_of_range_event["commence_time"] = "2024-08-15T00:00:00Z"
        payload["data"].append(out_of_range_event)
        return payload


def test_backfill_history_filters_events_outside_date_range(clean_db):
    game_start = datetime(2023, 6, 2, 0, 0, 0, tzinfo=UTC)
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-oa-hist-2",
            home_name="Minnesota Lynx",
            away_name="Connecticut Sun",
            start_time=game_start,
            status=GameStatus.FINAL,
        )
        # The out-of-range event's teams DO exist as canonical games
        # elsewhere in the season, to prove the exclusion is about the
        # DATE RANGE, not an unresolvable crosswalk.
        _seed_game(
            conn,
            external_id="espn-oa-hist-3",
            home_name="Chicago Sky",
            away_name="Indiana Fever",
            start_time=datetime(2024, 8, 15, 0, 0, 0, tzinfo=UTC),
            status=GameStatus.FINAL,
        )
        conn.commit()

    result = backfill_history(
        clean_db, FakeOddsApiHistoricalClientWithExtraEvent(), date(2023, 6, 1), date(2023, 6, 3)
    )
    with clean_db.connection() as conn:
        vendors = conn.execute(
            "SELECT g.home_team_id FROM sportsbook_game_odds sgo "
            "JOIN games g ON g.id = sgo.game_id WHERE sgo.source = 'the_odds_api'"
        ).fetchall()
    assert result.rows_inserted == 2  # only the in-range Lynx/Sun event's 2 bookmaker rows
    assert len(vendors) == 2


class FakeOddsApiScoresClient:
    def fetch_scores(self, *, days_from: int) -> object:
        del days_from
        return load_fixture("odds_api_scores.json")


def test_snapshot_current_scores_end_to_end_flags_a_real_mismatch(clean_db):
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-oa-score-1",
            home_name="Washington Mystics",
            away_name="Golden State Valkyries",
            start_time=datetime(2026, 7, 6, 23, 32, 43, tzinfo=UTC),
            home_score=49,
            away_score=62,
            status=GameStatus.FINAL,
        )
        # Deliberately WRONG score vs. the fixture's 89-90, to prove the
        # cross-check validation surfaces a real disagreement.
        mismatch_game_id = _seed_game(
            conn,
            external_id="espn-oa-score-2",
            home_name="Minnesota Lynx",
            away_name="Connecticut Sun",
            start_time=datetime(2026, 7, 7, 0, 2, 0, tzinfo=UTC),
            home_score=999,
            away_score=1,
            status=GameStatus.FINAL,
        )
        _seed_game(
            conn,
            external_id="espn-oa-score-3",
            home_name="Los Angeles Sparks",
            away_name="Seattle Storm",
            start_time=datetime(2026, 7, 7, 2, 7, 44, tzinfo=UTC),
            home_score=64,
            away_score=82,
            status=GameStatus.FINAL,
        )
        conn.commit()

    result = snapshot_current_scores(clean_db, FakeOddsApiScoresClient())
    # fixture has 3 completed games + 1 not-yet-started (parser-level
    # filtered, never reaches the pipeline)
    assert result.games_seen == 3
    assert result.rows_inserted == 3
    assert result.unresolved_games == 0

    with clean_db.connection() as conn:
        check = check_odds_api_score_matches_game_score(conn)
    assert not check.passed
    assert check.violation_count == 1
    assert f"game={mismatch_game_id}" in check.sample_violations[0]
    assert "games_score=999-1" in check.sample_violations[0]
    assert "odds_api_score=89-90" in check.sample_violations[0]


def test_snapshot_current_scores_clean_when_all_agree(clean_db):
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-oa-score-4",
            home_name="Washington Mystics",
            away_name="Golden State Valkyries",
            start_time=datetime(2026, 7, 6, 23, 32, 43, tzinfo=UTC),
            home_score=49,
            away_score=62,
            status=GameStatus.FINAL,
        )
        conn.commit()

    snapshot_current_scores(clean_db, FakeOddsApiScoresClient())
    with clean_db.connection() as conn:
        check = check_odds_api_score_matches_game_score(conn)
    assert check.passed
    assert check.violation_count == 0


def test_snapshot_current_scores_skips_unresolved_game(clean_db):
    # No games seeded -- every completed event in the fixture is unresolvable.
    result = snapshot_current_scores(clean_db, FakeOddsApiScoresClient())
    assert result.games_seen == 3
    assert result.unresolved_games == 3
    assert result.rows_inserted == 0
    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM odds_api_game_scores").fetchone()[0]
    assert count == 0
