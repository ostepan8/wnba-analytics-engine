"""End-to-end integration tests: balldontlie /wnba/v1/player_injuries
snapshot -> real Postgres.

Kept as its own file (many-small-files convention, same as
test_balldontlie_players_ingest_e2e.py) rather than folded into
test_ingestion_e2e.py. Same clean_db/FakeClient pattern as the rest of
tests/integration/ -- see that file's conftest module docstring for the
database-safety guarantees clean_db provides.

Field shapes below mirror the real payload captured live and trimmed into
tests/fixtures/balldontlie_player_injuries.json (see
test_injuries_parser.py for the parser-level assertions against that
fixture); these fake clients reuse the same real id/name/bio values
rather than inventing new ones.
"""

from __future__ import annotations

import pytest

from wnba_engine.pipeline.balldontlie_injury_ingest import snapshot_current_injuries
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration


def _team(team_id: int, abbreviation: str, city: str, name: str) -> dict[str, object]:
    return {
        "id": team_id,
        "conference": "Eastern Conference",
        "city": city,
        "name": name,
        "full_name": f"{city} {name}",
        "abbreviation": abbreviation,
    }


def _player(
    player_id: int, first_name: str, last_name: str, team: dict[str, object]
) -> dict[str, object]:
    return {
        "id": player_id,
        "first_name": first_name,
        "last_name": last_name,
        "position": "F",
        "position_abbreviation": "F",
        "height": "6' 2\"",
        "weight": "180 lbs",
        "jersey_number": "10",
        "college": "Somewhere",
        "age": 27,
        "team": team,
    }


class FakeBalldontlieInjuriesClient:
    """Single page, three real rows (two ATL, one PHX) -- the same trimmed
    live data as tests/fixtures/balldontlie_player_injuries.json."""

    def fetch_player_injuries_page(self, *, cursor: int | None = None, per_page: int = 100):
        del cursor, per_page
        atl = _team(4, "ATL", "Atlanta", "Dream")
        phx = _team(10, "PHX", "Phoenix", "Mercury")
        return {
            "data": [
                {
                    "player": _player(750, "Aaliyah", "Nye", atl),
                    "status": "Out",
                    "return_date": "Jul 9",
                    "comment": "Jul 8: Nye (knee) is questionable.",
                },
                {
                    "player": _player(495, "Brionna", "Jones", atl),
                    "status": "Out",
                    "return_date": "Jul 13",
                    "comment": None,
                },
                {
                    "player": _player(373, "Alyssa", "Thomas", phx),
                    "status": "Day-To-Day",
                    "return_date": "Jul 9",
                    "comment": "Jul 9: Thomas (foot) is probable.",
                },
            ],
            "meta": {"next_cursor": None, "per_page": 3},
        }


class FakeBalldontlieInjuriesUnresolvedTeamClient:
    """One row whose team abbreviation isn't a real WNBA team -- exercises
    the unresolved-team skip path (same contract as the standings/ESPN
    injury pipelines: no new team is ever originated from an
    abbreviation-only source)."""

    def fetch_player_injuries_page(self, *, cursor: int | None = None, per_page: int = 100):
        del cursor, per_page
        ghost = _team(999, "ZZZ", "Nowhere", "Ghosts")
        return {
            "data": [
                {
                    "player": _player(1, "Ghost", "Player", ghost),
                    "status": "Out",
                    "return_date": "Jul 9",
                    "comment": None,
                }
            ],
            "meta": {"next_cursor": None, "per_page": 1},
        }


def _seed_real_teams(clean_db) -> None:
    with clean_db.connection() as conn:
        conn.execute(
            "INSERT INTO teams (name, abbreviation) VALUES "
            "('Atlanta Dream', 'ATL'), ('Phoenix Mercury', 'PHX')"
        )
        conn.commit()


def test_balldontlie_injury_snapshot_end_to_end(clean_db):
    _seed_real_teams(clean_db)
    result = snapshot_current_injuries(clean_db, FakeBalldontlieInjuriesClient())

    assert result.pages_fetched == 1
    assert result.entries_seen == 3
    assert result.entries_inserted == 3
    assert result.unresolved_teams == 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT status, return_date_text, comment, source "
            "FROM balldontlie_injury_reports ORDER BY player_id"
        ).fetchall()
    assert len(rows) == 3
    by_status = {row[0] for row in rows}
    assert by_status == {"Out", "Day-To-Day"}
    assert all(row[3] == "balldontlie" for row in rows)
    null_comment_rows = [row for row in rows if row[2] is None]
    assert len(null_comment_rows) == 1


def test_balldontlie_injury_snapshot_originates_new_player(clean_db):
    # A balldontlie-only injured player (never in an ESPN box score) must
    # still originate a brand-new canonical player row, same contract as
    # the players sweep.
    _seed_real_teams(clean_db)
    with clean_db.connection() as conn:
        assert entity_repo.find_player_by_name(conn, "Aaliyah Nye") is None

    snapshot_current_injuries(clean_db, FakeBalldontlieInjuriesClient())

    with clean_db.connection() as conn:
        player_id = entity_repo.find_player_by_name(conn, "Aaliyah Nye")
        bdl_id = entity_repo.lookup_internal_id(conn, "balldontlie", "player", "750")
    assert player_id is not None
    assert bdl_id == player_id


def test_balldontlie_injury_snapshot_rerun_appends_fresh_rows(clean_db):
    # Append-only-per-fetch, same philosophy as ESPN's injury_reports --
    # a rerun with unchanged data must produce a SECOND set of rows, not
    # upsert over the first.
    _seed_real_teams(clean_db)
    snapshot_current_injuries(clean_db, FakeBalldontlieInjuriesClient())
    rerun = snapshot_current_injuries(clean_db, FakeBalldontlieInjuriesClient())
    assert rerun.entries_inserted == 3

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM balldontlie_injury_reports").fetchone()[0]
    assert count == 6


def test_balldontlie_injury_snapshot_skips_unresolved_team(clean_db):
    _seed_real_teams(clean_db)
    result = snapshot_current_injuries(clean_db, FakeBalldontlieInjuriesUnresolvedTeamClient())

    assert result.entries_seen == 1
    assert result.entries_inserted == 0
    assert result.unresolved_teams == 1

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM balldontlie_injury_reports").fetchone()[0]
        player_count = conn.execute("SELECT count(*) FROM players").fetchone()[0]
    assert count == 0
    # Team never resolved, so the player was never even looked up/created.
    assert player_count == 0
