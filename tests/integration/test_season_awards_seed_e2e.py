"""End-to-end integration tests: the season_awards seed script -> real
Postgres.

Same clean_db pattern as the rest of tests/integration/ -- see
conftest.py's module docstring for the database-safety guarantees
clean_db provides. Uses small, synthetic `records` tuples (not the full
SEASON_AWARD_WINNERS dataset from season_awards_data.py) so each test
exercises one behavior in isolation against a controlled players/teams
fixture, rather than depending on which of ~120 real historical names
happen to already exist in a given test database.
"""

from __future__ import annotations

import pytest

from wnba_engine.models.season_awards import AwardWinner
from wnba_engine.pipeline.season_awards_seed import seed_season_awards

pytestmark = pytest.mark.integration


def _seed_team_and_player(clean_db, *, team_name: str, abbreviation: str, player_name: str) -> None:
    with clean_db.connection() as conn:
        conn.execute(
            "INSERT INTO teams (name, abbreviation) VALUES (%s, %s)",
            (team_name, abbreviation),
        )
        conn.execute("INSERT INTO players (full_name) VALUES (%s)", (player_name,))
        conn.commit()


def test_seed_resolves_existing_player_to_player_id(clean_db):
    _seed_team_and_player(
        clean_db, team_name="Las Vegas Aces", abbreviation="LVA", player_name="A'ja Wilson"
    )
    records = (
        AwardWinner(season=2024, award="mvp", raw_name="A'ja Wilson", source="https://example.com"),
    )

    result = seed_season_awards(clean_db, records)

    assert result.rows_inserted == 1
    assert result.players_resolved == 1
    assert result.unresolved_names == ()

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT sa.player_id, sa.raw_name, p.full_name "
            "FROM season_awards sa JOIN players p ON p.id = sa.player_id "
            "WHERE sa.season = 2024 AND sa.award = 'mvp'"
        ).fetchone()
    assert row is not None
    player_id, raw_name, full_name = row
    assert raw_name == "A'ja Wilson"
    assert full_name == "A'ja Wilson"


def test_seed_stores_raw_name_with_null_player_id_when_unresolved(clean_db):
    # No players seeded at all -- every name is a guaranteed miss.
    records = (
        AwardWinner(
            season=2024, award="roy", raw_name="Nobody Everheardof", source="https://example.com"
        ),
    )

    result = seed_season_awards(clean_db, records)

    assert result.rows_inserted == 1
    assert result.players_resolved == 0
    assert result.unresolved_names == ("Nobody Everheardof",)

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT player_id, raw_name FROM season_awards WHERE season = 2024 AND award = 'roy'"
        ).fetchone()
    assert row == (None, "Nobody Everheardof")


def test_seed_is_idempotent_on_rerun(clean_db):
    _seed_team_and_player(
        clean_db,
        team_name="New York Liberty",
        abbreviation="NYL",
        player_name="Breanna Stewart",
    )
    records = (
        AwardWinner(
            season=2023, award="mvp", raw_name="Breanna Stewart", source="https://example.com"
        ),
    )

    first = seed_season_awards(clean_db, records)
    second = seed_season_awards(clean_db, records)

    assert first.rows_inserted == 1
    assert second.rows_inserted == 0
    assert second.rows_already_present == 1

    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM season_awards WHERE season = 2023 AND award = 'mvp'"
        ).fetchone()[0]
    assert count == 1


def test_seed_resolves_coach_of_the_year_team_not_player(clean_db):
    _seed_team_and_player(
        clean_db, team_name="Minnesota Lynx", abbreviation="MIN", player_name="Someone Else"
    )
    records = (
        AwardWinner(
            season=2024,
            award="coy",
            raw_name="Cheryl Reeve",
            source="https://example.com",
            coach_team_name="Minnesota Lynx",
        ),
    )

    result = seed_season_awards(clean_db, records)

    assert result.rows_inserted == 1
    # Coach of the Year never looks up a player -- the coach's name isn't
    # in the players table at all.
    assert result.players_resolved == 0
    assert result.coach_teams_resolved == 1

    with clean_db.connection() as conn:
        row = conn.execute(
            "SELECT sa.player_id, sa.raw_name, t.name "
            "FROM season_awards sa JOIN teams t ON t.id = sa.team_id "
            "WHERE sa.season = 2024 AND sa.award = 'coy'"
        ).fetchone()
    assert row is not None
    player_id, raw_name, team_name = row
    assert player_id is None
    assert raw_name == "Cheryl Reeve"
    assert team_name == "Minnesota Lynx"


def test_seed_distinguishes_all_wnba_first_and_second_team_selection(clean_db):
    _seed_team_and_player(
        clean_db, team_name="Seattle Storm", abbreviation="SEA", player_name="Player One"
    )
    with clean_db.connection() as conn:
        conn.execute("INSERT INTO players (full_name) VALUES ('Player Two')")
        conn.commit()

    records = (
        AwardWinner(
            season=2024,
            award="all_wnba",
            raw_name="Player One",
            source="https://example.com",
            team_selection="first",
        ),
        AwardWinner(
            season=2024,
            award="all_wnba",
            raw_name="Player Two",
            source="https://example.com",
            team_selection="second",
        ),
    )

    result = seed_season_awards(clean_db, records)

    assert result.rows_inserted == 2
    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT raw_name, team_selection FROM season_awards "
            "WHERE season = 2024 AND award = 'all_wnba' ORDER BY raw_name"
        ).fetchall()
    assert rows == [("Player One", "first"), ("Player Two", "second")]


def test_seed_same_raw_name_different_team_selection_does_not_collide(clean_db):
    # Same (season, award, raw_name) but different team_selection must be
    # treated as two distinct rows, not deduped against each other -- the
    # unique index is keyed on all four columns together.
    records = (
        AwardWinner(
            season=2024,
            award="all_defense",
            raw_name="Same Player",
            source="https://example.com",
            team_selection="first",
        ),
        AwardWinner(
            season=2024,
            award="all_defense",
            raw_name="Same Player",
            source="https://example.com",
            team_selection="second",
        ),
    )

    result = seed_season_awards(clean_db, records)

    assert result.rows_inserted == 2
    with clean_db.connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM season_awards WHERE season = 2024 AND award = 'all_defense'"
        ).fetchone()[0]
    assert count == 2
