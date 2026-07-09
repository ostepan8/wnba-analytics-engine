"""End-to-end integration tests: ESPN transactions -> real Postgres.

Same clean_db/FakeClient pattern as the rest of tests/integration/ -- see
test_balldontlie_players_ingest_e2e.py's module docstring for the
database-safety guarantees clean_db provides. Descriptions below are real
text observed live (see test_transaction_classifier.py), reused here to
exercise the full pipeline: team crosswalk resolution, best-effort
type/player classification, player crosswalk resolution, and idempotent
re-runs against the append-only player_transactions table.
"""

from __future__ import annotations

import pytest

from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.models.games import TeamRef
from wnba_engine.pipeline.espn_transactions_ingest import backfill_season
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration


def _team(external_id: str, name: str, abbreviation: str) -> dict[str, object]:
    return {"id": external_id, "displayName": name, "abbreviation": abbreviation}


class FakeEspnTransactionsSinglePageClient:
    """One page, four rows: a resolvable player signing, a coaching/
    front-office move (no player), a resolvable player waiver for an
    UNKNOWN team (never seeded -- exercises team_id=NULL), and a signing
    for a player name that won't resolve to any canonical player (exercises
    player_id=NULL / raw_player_name-only)."""

    def fetch_transactions(self, season: int, page: int = 1, limit: int = 200) -> object:
        del season, page, limit
        return {
            "count": 4,
            "pageCount": 1,
            "transactions": [
                {
                    "date": "2024-05-01T08:00Z",
                    "description": "Signed G Kate Martin to a rookie scale contract.",
                    "team": _team("5", "Indiana Fever", "IND"),
                },
                {
                    "date": "2024-04-15T08:00Z",
                    "description": "Named Clare Duwelius general manager.",
                    "team": _team("8", "Minnesota Lynx", "MIN"),
                },
                {
                    "date": "2024-06-01T08:00Z",
                    "description": "Waived F Random Player.",
                    "team": _team("999", "Unknown Expansion Team", "UNK"),
                },
                {
                    "date": "2024-06-10T08:00Z",
                    "description": "Signed G Never Before Seen to a hardship contract.",
                    "team": _team("5", "Indiana Fever", "IND"),
                },
            ],
        }


class FakeEspnTransactionsTwoPageClient:
    """Two pages (3 rows on page 1, 2 rows on page 2) -- exercises the
    pageCount-driven page loop in backfill_season, mirroring the real
    season=2025 response (count=220, pageCount=2)."""

    def fetch_transactions(self, season: int, page: int = 1, limit: int = 200) -> object:
        del season, limit
        if page == 1:
            return {
                "count": 5,
                "pageCount": 2,
                "transactions": [
                    {
                        "date": "2025-01-10T08:00Z",
                        "description": "Waived G Aari McDonald.",
                        "team": _team("6", "Los Angeles Sparks", "LA"),
                    },
                    {
                        "date": "2025-01-11T08:00Z",
                        "description": "Released C Elizabeth Kitley.",
                        "team": _team("6", "Los Angeles Sparks", "LA"),
                    },
                    {
                        "date": "2025-01-12T08:00Z",
                        "description": "Claimed G Grace Berger off waivers.",
                        "team": _team("6", "Los Angeles Sparks", "LA"),
                    },
                ],
            }
        return {
            "count": 5,
            "pageCount": 2,
            "transactions": [
                {
                    "date": "2025-02-01T08:00Z",
                    "description": "Signed F Camryn Taylor to a training camp contract.",
                    "team": _team("6", "Los Angeles Sparks", "LA"),
                },
                {
                    "date": "2025-02-02T08:00Z",
                    "description": "Hired Stephanie White as head coach.",
                    "team": _team("6", "Los Angeles Sparks", "LA"),
                },
            ],
        }


def _seed_espn_team(conn, external_id: str, name: str, abbreviation: str) -> int:
    return entity_repo.resolve_or_create_team(
        conn, "espn", TeamRef(external_id=external_id, name=name, abbreviation=abbreviation)
    )


def _seed_espn_player(conn, external_id: str, full_name: str) -> int:
    return entity_repo.resolve_or_create_player(
        conn, "espn", PlayerRef(external_id=external_id, full_name=full_name, position=None)
    )


def test_backfill_season_resolves_teams_players_and_classifies_type(clean_db):
    with clean_db.connection() as conn:
        _seed_espn_team(conn, "5", "Indiana Fever", "IND")
        _seed_espn_team(conn, "8", "Minnesota Lynx", "MIN")
        _seed_espn_player(conn, "101", "Kate Martin")
        conn.commit()

    result = backfill_season(clean_db, FakeEspnTransactionsSinglePageClient(), 2024)

    assert result.transactions_seen == 4
    assert result.rows_inserted == 4
    assert result.rows_skipped_duplicate == 0
    assert result.teams_resolved == 3  # Fever x2, Lynx x1
    assert result.teams_unresolved == 1  # the "999" unknown expansion team
    assert result.players_resolved == 1  # Kate Martin
    assert result.players_raw_only == 2  # "Random Player" + "Never Before Seen" -- no match
    assert result.players_unclassified == 1  # the GM move -- no position token, no name at all

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT transaction_type, team_id, raw_team_name, player_id, raw_player_name, "
            "description FROM player_transactions ORDER BY transaction_date"
        ).fetchall()
    assert len(rows) == 4

    gm_row = next(r for r in rows if "general manager" in r[5])
    assert gm_row[0] == "front_office"
    assert gm_row[3] is None  # player_id
    assert gm_row[4] is None  # raw_player_name -- no position token in the GM description

    signed_row = next(r for r in rows if "Kate Martin" in r[5])
    assert signed_row[0] == "signed"
    assert signed_row[3] is not None  # resolved player_id
    assert signed_row[4] == "Kate Martin"

    unresolved_team_row = next(r for r in rows if r[5] == "Waived F Random Player.")
    assert unresolved_team_row[1] is None  # team_id NULL, never dropped
    assert unresolved_team_row[2] == "Unknown Expansion Team"  # raw name preserved
    assert unresolved_team_row[0] == "waived"
    assert unresolved_team_row[4] == "Random Player"  # raw_player_name still extracted

    unresolved_player_row = next(r for r in rows if "Never Before Seen" in r[5])
    assert unresolved_player_row[3] is None  # player_id NULL
    assert unresolved_player_row[4] == "Never Before Seen"  # raw name preserved


def test_backfill_season_paginates_across_multiple_pages(clean_db):
    with clean_db.connection() as conn:
        _seed_espn_team(conn, "6", "Los Angeles Sparks", "LA")
        conn.commit()

    result = backfill_season(clean_db, FakeEspnTransactionsTwoPageClient(), 2025)

    assert result.transactions_seen == 5
    assert result.rows_inserted == 5

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM player_transactions").fetchone()[0]
    assert count == 5


def test_backfill_season_is_idempotent_on_rerun(clean_db):
    with clean_db.connection() as conn:
        _seed_espn_team(conn, "5", "Indiana Fever", "IND")
        _seed_espn_team(conn, "8", "Minnesota Lynx", "MIN")
        conn.commit()

    client = FakeEspnTransactionsSinglePageClient()
    first = backfill_season(clean_db, client, 2024)
    second = backfill_season(clean_db, client, 2024)

    assert first.rows_inserted == 4
    assert second.rows_inserted == 0
    assert second.rows_skipped_duplicate == 4

    with clean_db.connection() as conn:
        count = conn.execute("SELECT count(*) FROM player_transactions").fetchone()[0]
    assert count == 4


def test_description_always_stored_verbatim_even_when_unclassified(clean_db):
    with clean_db.connection() as conn:
        _seed_espn_team(conn, "5", "Indiana Fever", "IND")
        _seed_espn_team(conn, "8", "Minnesota Lynx", "MIN")
        conn.commit()

    backfill_season(clean_db, FakeEspnTransactionsSinglePageClient(), 2024)

    with clean_db.connection() as conn:
        descriptions = {
            row[0] for row in conn.execute("SELECT description FROM player_transactions")
        }
    assert "Named Clare Duwelius general manager." in descriptions
    assert "Signed G Kate Martin to a rookie scale contract." in descriptions
