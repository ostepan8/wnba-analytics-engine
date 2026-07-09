"""End-to-end integration tests: balldontlie /wnba/v1/players sweep ->
real Postgres.

Kept as its own file (rather than folded into test_ingestion_e2e.py,
already 1900+ lines) per the "many small files" convention. Same
clean_db/FakeClient pattern as the rest of tests/integration/ -- see that
file's module docstring for the database-safety guarantees clean_db
provides.

Field shapes below mirror the real payload captured live and trimmed into
tests/fixtures/balldontlie_players.json (see test_players_parser.py for
the parser-level assertions against that fixture); these fake clients
reuse the same real id/name/bio values rather than inventing new ones.
"""

from __future__ import annotations

import pytest

from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.pipeline.balldontlie_players_ingest import backfill_players
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration


class FakeBalldontlieAllPlayersClient:
    """Single page, three real rows (sparse/partial/full bio) -- the same
    trimmed live data as tests/fixtures/balldontlie_players.json."""

    def fetch_players_page(self, *, cursor: int | None = None, per_page: int = 100):
        del cursor, per_page
        return {
            "data": [
                {
                    "id": 1,
                    "first_name": "Tina",
                    "last_name": "Thompson",
                    "position": "Forward",
                    "position_abbreviation": "F",
                    "height": None,
                    "weight": None,
                    "jersey_number": None,
                    "college": None,
                    "age": None,
                    "team": {"id": 15, "abbreviation": "HOU"},
                },
                {
                    "id": 336,
                    "first_name": "Layshia",
                    "last_name": "Clarendon",
                    "position": "Guard",
                    "position_abbreviation": "G",
                    "height": None,
                    "weight": None,
                    "jersey_number": "5",
                    "college": None,
                    "age": None,
                    "team": {"id": 3, "abbreviation": "IND"},
                },
                {
                    "id": 242,
                    "first_name": "DeWanna",
                    "last_name": "Bonner",
                    "position": "F",
                    "position_abbreviation": "F",
                    "height": "6' 4\"",
                    "weight": "140 lbs",
                    "jersey_number": "24",
                    "college": "Auburn",
                    "age": 38,
                    "team": {"id": 10, "abbreviation": "PHX"},
                },
            ],
            "meta": {"next_cursor": None, "per_page": 3},
        }


def test_balldontlie_players_backfill_end_to_end(clean_db):
    result = backfill_players(clean_db, FakeBalldontlieAllPlayersClient())
    assert result.pages_fetched == 1
    assert result.players_seen == 3
    assert result.players_processed == 3

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT height, weight, jersey_number, college, age "
            "FROM players WHERE full_name = 'DeWanna Bonner'"
        ).fetchone()
    assert row == ("6' 4\"", "140 lbs", "24", "Auburn", 38)

    with clean_db.connection() as conn:
        sparse = conn.execute(
            "SELECT height, weight, jersey_number, college, age "
            "FROM players WHERE full_name = 'Tina Thompson'"
        ).fetchone()
    assert sparse == (None, None, None, None, None)

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM players").fetchone()[0]
    assert count == 3


def test_balldontlie_players_backfill_is_idempotent_on_rerun(clean_db):
    backfill_players(clean_db, FakeBalldontlieAllPlayersClient())
    rerun = backfill_players(clean_db, FakeBalldontlieAllPlayersClient())
    assert rerun.players_processed == 3

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM players").fetchone()[0]
    assert count == 3


_PAGE_SIZE = 100  # must match balldontlie_players_ingest.PAGE_SIZE


def _synthetic_player_row(player_id: int) -> dict[str, object]:
    return {
        "id": player_id,
        "first_name": "Synthetic",
        "last_name": f"Player{player_id}",
        "position": "G",
        "height": None,
        "weight": None,
        "jersey_number": None,
        "college": None,
        "age": None,
        "team": {"id": 1, "abbreviation": "HOU"},
    }


class FakeBalldontliePagedPlayersClient:
    """Two pages -- exercises the cursor-pagination loop
    (fetch_players_page(cursor=...) -> meta.next_cursor). Real balldontlie
    pages are always full (per_page rows) except the genuinely last page
    (verified live: walking all 859 players returned exactly 100 rows/page
    for every page but the ninth), so page one here returns a FULL page --
    a page short of per_page with more cursor to follow never happens in
    practice, and the pipeline's own len(rows) < PAGE_SIZE early-exit
    (mirroring balldontlie_shot_zone_ingest.py) relies on that."""

    def fetch_players_page(self, *, cursor: int | None = None, per_page: int = 100):
        del per_page
        if cursor is None:
            rows = [_synthetic_player_row(i) for i in range(1, _PAGE_SIZE + 1)]
            return {"data": rows, "meta": {"next_cursor": _PAGE_SIZE, "per_page": _PAGE_SIZE}}
        return {
            "data": [
                {
                    "id": 242,
                    "first_name": "DeWanna",
                    "last_name": "Bonner",
                    "position": "F",
                    "height": "6' 4\"",
                    "weight": "140 lbs",
                    "jersey_number": "24",
                    "college": "Auburn",
                    "age": 38,
                    "team": {"id": 10, "abbreviation": "PHX"},
                }
            ],
            "meta": {"per_page": _PAGE_SIZE},  # final page: next_cursor absent (verified live)
        }


def test_balldontlie_players_backfill_paginates_across_multiple_pages(clean_db):
    result = backfill_players(clean_db, FakeBalldontliePagedPlayersClient())
    assert result.pages_fetched == 2
    assert result.players_seen == _PAGE_SIZE + 1
    assert result.players_processed == _PAGE_SIZE + 1

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM players").fetchone()[0]
    assert count == _PAGE_SIZE + 1


def test_balldontlie_players_backfill_matches_existing_espn_player_by_name(clean_db):
    # The players sweep must join onto a canonical player ESPN's box
    # scores already created (matched by name), not fork a duplicate --
    # same crosswalk contract as the advanced-stats/shot-zone pipelines.
    with clean_db.connection() as conn:
        espn_id = entity_repo.resolve_or_create_player(
            conn, "espn", PlayerRef(external_id="1068", full_name="DeWanna Bonner", position="F")
        )
        conn.commit()

    result = backfill_players(clean_db, FakeBalldontlieAllPlayersClient())
    assert result.players_processed == 3

    with clean_db.connection() as conn:
        bdl_id = entity_repo.lookup_internal_id(conn, "balldontlie", "player", "242")
        count = conn.execute("SELECT count(*) FROM players").fetchone()[0]
    assert bdl_id == espn_id
    assert count == 3  # matched onto the ESPN row, not +1 new row


def test_balldontlie_players_backfill_can_originate_new_canonical_player(clean_db):
    # Unlike advanced-stats/shot-zone (which only ever match an EXISTING
    # ESPN-originated player by name), the players sweep can be the FIRST
    # pipeline to ever see a given player -- e.g. a retired/inactive
    # player ESPN's current-season box scores never mention. That run
    # must originate a brand-new canonical player row, not skip the row.
    with clean_db.connection() as conn:
        assert entity_repo.find_player_by_name(conn, "Tina Thompson") is None

    result = backfill_players(clean_db, FakeBalldontlieAllPlayersClient())
    assert result.players_processed == 3

    with clean_db.connection() as conn:
        player_id = entity_repo.find_player_by_name(conn, "Tina Thompson")
        bdl_id = entity_repo.lookup_internal_id(conn, "balldontlie", "player", "1")
    assert player_id is not None
    assert bdl_id == player_id
