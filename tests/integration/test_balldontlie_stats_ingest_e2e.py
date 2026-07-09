"""End-to-end integration tests: balldontlie TRADITIONAL box score stats
(/wnba/v1/player_stats, /wnba/v1/team_stats) -> real Postgres.

Kept as its own file (rather than folded into the already-huge
test_ingestion_e2e.py) per the "many small files" convention. Same
clean_db/FakeClient pattern as the rest of tests/integration/.

The whole point of this feature is that team_game_stats/player_game_stats
were designed from the start to hold multiple providers' box scores side
by side for the SAME game (see db/migrations/0002_box_scores.sql's
PRIMARY KEY (game_id, ..., source)). These tests seed an ESPN box score
first (source='espn'), then ingest a balldontlie traditional box score for
the SAME game/teams/player (source='balldontlie') and prove both rows
coexist without a primary-key collision -- that's the actual feature under
test, not just "the parser parses."

Team/game identifiers below reuse the SAME NY-vs-SEA, 2025-07-06 game and
Nneka Ogwumike (ESPN external_id '1068') that
test_balldontlie_advanced_stats_backfill_end_to_end already uses to prove
its crosswalk, for the same reason: it lets the balldontlie row resolve
onto entities ESPN's fixture already created. The traditional stat VALUES
themselves are the real captured payload from tests/fixtures/
balldontlie_player_stats.json / balldontlie_team_stats.json (Sonia
Citron's and the ATL/WSH team rows), with only the id/team/game
identifiers substituted to match this fixture's canonical game.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.pipeline.balldontlie_stats_ingest import backfill_season
from wnba_engine.pipeline.espn_ingest import sync_date
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())


class FakeEspnClient:
    """Same NY vs SEA, 2025-07-06 fixture game used across
    tests/integration/test_ingestion_e2e.py."""

    def fetch_scoreboard(self, day: date) -> object:
        payload = load_fixture("espn_scoreboard.json")
        return {"events": [e for e in payload["events"] if e["id"] == "401736228"]}

    def fetch_summary(self, event_id: str) -> object:
        assert event_id == "401736228"
        return load_fixture("espn_summary.json")


class FakeBalldontlieStatsClient:
    """One game matching the ESPN fixture's NY vs SEA, 2025-07-06 game, two
    team-stats rows, and one player-stats row for Nneka Ogwumike (ESPN
    external_id '1068' in the summary fixture) -- to prove the crosswalk
    lands on the SAME canonical game/teams/player ESPN's box score already
    created. Stat values are the real payload captured live for game 3858
    (tests/fixtures/balldontlie_team_stats.json / balldontlie_player_stats
    .json), with id/team/game identifiers substituted."""

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

    def fetch_team_stats_page(self, season: int, *, cursor: int | None = None, per_page: int = 100):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "team": {"id": 1, "full_name": "New York Liberty", "abbreviation": "NY"},
                    "game": {"id": 9001, "date": "2025-07-06T17:00:00.000Z", "season": 2025},
                    "fgm": 30,
                    "fga": 74,
                    "fg3m": 12,
                    "fg3a": 36,
                    "ftm": 18,
                    "fta": 27,
                    "oreb": 15,
                    "dreb": 22,
                    "reb": 37,
                    "ast": 24,
                    "stl": 4,
                    "blk": 2,
                    "turnovers": 14,
                    "fouls": 22,
                },
                {
                    "team": {"id": 2, "full_name": "Seattle Storm", "abbreviation": "SEA"},
                    "game": {"id": 9001, "date": "2025-07-06T17:00:00.000Z", "season": 2025},
                    "fgm": 31,
                    "fga": 61,
                    "fg3m": 9,
                    "fg3a": 18,
                    "ftm": 23,
                    "fta": 31,
                    "oreb": 5,
                    "dreb": 21,
                    "reb": 26,
                    "ast": 18,
                    "stl": 7,
                    "blk": 4,
                    "turnovers": 7,
                    "fouls": 25,
                },
            ],
            "meta": {"next_cursor": None, "per_page": 2},
        }

    def fetch_player_stats_page(
        self, season: int, *, cursor: int | None = None, per_page: int = 100
    ):
        del season, cursor, per_page
        return {
            "data": [
                {
                    "player": {
                        "id": 777,
                        "first_name": "Nneka",
                        "last_name": "Ogwumike",
                        "position": "F",
                        "height": "6' 2\"",
                        "weight": "195 lbs",
                        "jersey_number": "30",
                        "college": "Stanford",
                        "age": 34,
                    },
                    "team": {"id": 2, "full_name": "Seattle Storm", "abbreviation": "SEA"},
                    "game": {"id": 9001, "date": "2025-07-06T17:00:00.000Z", "season": 2025},
                    "min": "24",
                    "fgm": 6,
                    "fga": 7,
                    "fg3m": 2,
                    "fg3a": 2,
                    "ftm": 5,
                    "fta": 6,
                    "oreb": None,
                    "dreb": 2,
                    "reb": 2,
                    "ast": 2,
                    "stl": None,
                    "blk": None,
                    "turnover": 1,
                    "pf": 4,
                    "pts": 19,
                    "plus_minus": 3,
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }


def test_balldontlie_stats_backfill_end_to_end(clean_db):
    espn_result = sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))
    assert espn_result.box_scores_ingested == 1

    result = backfill_season(clean_db, FakeBalldontlieStatsClient(), 2025)
    assert result.games_seen == 1
    assert result.games_resolved == 1
    assert result.games_unresolved == 0
    assert result.team_rows_seen == 2
    assert result.team_rows_inserted == 2
    assert result.unresolved_games_for_team_stats == 0
    assert result.unresolved_teams_for_team_stats == 0
    assert result.player_rows_seen == 1
    assert result.player_rows_inserted == 1
    assert result.unresolved_games_for_player_stats == 0
    assert result.unresolved_teams_for_player_stats == 0


def test_balldontlie_team_stats_coexist_with_espn_for_same_game(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds source='espn' rows
    backfill_season(clean_db, FakeBalldontlieStatsClient(), 2025)

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT source, count(*) FROM team_game_stats GROUP BY source ORDER BY source"
        ).fetchall()
    assert dict(rows) == {"balldontlie": 2, "espn": 2}

    with clean_db.connection() as conn:
        bdl_row = conn.execute(
            "SELECT field_goals_made, field_goals_attempted, rebounds, turnovers "
            "FROM team_game_stats t "
            "JOIN teams tm ON tm.id = t.team_id "
            "WHERE t.source = 'balldontlie' AND tm.abbreviation = 'NY'"
        ).fetchone()
    assert bdl_row == (30, 74, 37, 14)


def test_balldontlie_player_stats_coexist_with_espn_for_same_player_and_game(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))  # seeds source='espn' rows
    backfill_season(clean_db, FakeBalldontlieStatsClient(), 2025)

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT source, count(*) FROM player_game_stats GROUP BY source ORDER BY source"
        ).fetchall()
    assert dict(rows) == {"balldontlie": 1, "espn": 8}

    # Crosswalk correctness: balldontlie's player id must resolve to the
    # SAME canonical player ESPN's box score already created (external_id
    # '1068' in the summary fixture), not a forked duplicate identity --
    # and that SAME (game_id, player_id) pair now has two rows, one per
    # source, proving the composite PRIMARY KEY (game_id, player_id,
    # source) actually allows this without collision.
    with clean_db.connection() as conn:
        espn_player_id = entity_repo.lookup_internal_id(conn, "espn", "player", "1068")
        bdl_player_id = entity_repo.lookup_internal_id(conn, "balldontlie", "player", "777")
        both_rows = conn.execute(
            "SELECT source, points, rebounds, assists FROM player_game_stats "
            "WHERE player_id = %s ORDER BY source",
            (espn_player_id,),
        ).fetchall()
    assert espn_player_id is not None
    assert bdl_player_id == espn_player_id
    assert len(both_rows) == 2
    sources = [row[0] for row in both_rows]
    assert sources == ["balldontlie", "espn"]
    bdl_row = both_rows[0]
    assert bdl_row == ("balldontlie", 19, 2, 2)


def test_balldontlie_stats_backfill_is_idempotent_on_rerun(clean_db):
    sync_date(clean_db, FakeEspnClient(), date(2025, 7, 6))
    backfill_season(clean_db, FakeBalldontlieStatsClient(), 2025)
    rerun = backfill_season(clean_db, FakeBalldontlieStatsClient(), 2025)
    assert rerun.team_rows_inserted == 2
    assert rerun.player_rows_inserted == 1

    with clean_db.connection() as conn:
        team_count = conn.execute(
            "SELECT count(*) FROM team_game_stats WHERE source = 'balldontlie'"
        ).fetchone()[0]
        player_count = conn.execute(
            "SELECT count(*) FROM player_game_stats WHERE source = 'balldontlie'"
        ).fetchone()[0]
    assert team_count == 2
    assert player_count == 1


def test_balldontlie_stats_backfill_skips_unresolved_game(clean_db):
    # No ESPN seed at all -- the balldontlie game can never resolve to a
    # canonical game, so every row is skipped, not errored.
    result = backfill_season(clean_db, FakeBalldontlieStatsClient(), 2025)
    assert result.games_resolved == 0
    assert result.games_unresolved == 1
    assert result.team_rows_inserted == 0
    assert result.unresolved_games_for_team_stats == 2
    assert result.player_rows_inserted == 0
    assert result.unresolved_games_for_player_stats == 1


def test_balldontlie_stats_backfill_originates_player_from_espn_reference(clean_db):
    # Sanity check that resolve_or_create_player_by_name is actually being
    # used with a real PlayerRef-compatible identity (mirrors the
    # advanced-stats crosswalk test).
    with clean_db.connection() as conn:
        espn_id = entity_repo.resolve_or_create_player(
            conn,
            "espn",
            PlayerRef(external_id="1068", full_name="Nneka Ogwumike", position="F"),
        )
        conn.commit()
    assert espn_id is not None
