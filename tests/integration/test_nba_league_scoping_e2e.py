"""NBA expansion (NBA_EXPANSION.md, Option A): teams/games/players are now
scoped by `league`, and provider_entity_map crosswalk strings are
league-specific where a provider's external ids are not globally unique.

This is a REGRESSION test for a real bug caught during that expansion's own
testing, not a hypothetical: ESPN's site API reuses small per-sport integer
team ids across leagues. Confirmed live 2026-08-22 -- WNBA's Minnesota Lynx
and NBA's Detroit Pistons BOTH carry ESPN team id "8". A shared `provider =
"espn"` string for both leagues let an NBA ingest's crosswalk lookup match
an existing WNBA team row and overwrite its name/abbreviation. The fixtures
here (espn_scoreboard_wnba_min_lynx.json, espn_scoreboard_nba.json) are
trimmed from the real live payloads that exposed this, per this project's
"fixtures come from real captured data" convention.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from wnba_engine.models.games import TeamRef
from wnba_engine.pipeline.espn_ingest import sync_date
from wnba_engine.repositories import entity_repo

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())


class FakeEspnClientWnba:
    provider = "espn"

    def fetch_scoreboard(self, day: date) -> object:
        return load_fixture("espn_scoreboard_wnba_min_lynx.json")

    def fetch_summary(self, event_id: str) -> object:
        raise AssertionError("this game is not final; summary should not be fetched")


class FakeEspnClientNba:
    provider = "espn_nba"

    def fetch_scoreboard(self, day: date) -> object:
        return load_fixture("espn_scoreboard_nba.json")

    def fetch_summary(self, event_id: str) -> object:
        raise AssertionError("this game is not final; summary should not be fetched")


def test_espn_team_id_collision_does_not_merge_across_leagues(clean_db):
    """The regression. Both ingests use ESPN team id '8' for their home
    team (Minnesota Lynx / Detroit Pistons) -- they must resolve to two
    distinct canonical teams, not one merged/overwritten row."""
    sync_date(clean_db, FakeEspnClientWnba(), date(2026, 6, 15), league="wnba")
    sync_date(clean_db, FakeEspnClientNba(), date(2026, 10, 20), league="nba")

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT name, abbreviation, league FROM teams WHERE abbreviation IN ('MIN', 'DET') "
            "ORDER BY league"
        ).fetchall()

    assert rows == [
        ("Detroit Pistons", "DET", "nba"),
        ("Minnesota Lynx", "MIN", "wnba"),
    ]


def test_find_team_by_abbreviation_is_league_scoped(clean_db):
    """A second real cross-league collision candidate: 'MIN' is a real
    abbreviation in both leagues today (Lynx / Timberwolves), even though
    this fixture pair happens to use Pistons for the NBA side."""
    with clean_db.connection() as conn:
        wnba_id = entity_repo.resolve_or_create_team(
            conn,
            "espn",
            TeamRef(external_id="8", name="Minnesota Lynx", abbreviation="MIN", league="wnba"),
        )
        nba_id = entity_repo.resolve_or_create_team(
            conn,
            "espn_nba",
            TeamRef(
                external_id="8", name="Minnesota Timberwolves", abbreviation="MIN", league="nba"
            ),
        )
        conn.commit()

        assert wnba_id != nba_id
        assert entity_repo.find_team_by_abbreviation(conn, "MIN", league="wnba") == wnba_id
        assert entity_repo.find_team_by_abbreviation(conn, "MIN", league="nba") == nba_id
        assert entity_repo.find_team_by_abbreviation(conn, "MIN") == wnba_id  # default unchanged


def test_league_column_defaults_to_wnba_for_existing_rows(clean_db):
    """Pre-expansion callers that never pass `league` must keep writing
    'wnba' rows -- the whole point of a default rather than a required
    parameter threaded through every existing call site."""
    from wnba_engine.models.games import TeamRef

    with clean_db.connection() as conn:
        team_id = entity_repo.resolve_or_create_team(
            conn, "espn", TeamRef(external_id="999", name="Test Team", abbreviation="TST")
        )
        conn.commit()
        row = conn.execute("SELECT league FROM teams WHERE id = %s", (team_id,)).fetchone()

    assert row[0] == "wnba"
