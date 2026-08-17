"""The guard against an incomplete schedule.

This check exists because of a failure that looked like a modelling bug and was
a data one. `sync-recent` reached only seven days ahead, so fixtures further out
were never ingested: in August 2026 the table held 33-37 regular-season games
per team out of 44. No row was wrong. The missing ones simply did not exist.

The damage was not a blank cell. Games remaining is counted from scheduled
games, so every team appeared to have none left and the playoff page reported
eleven teams as mathematically eliminated when the true number was two. A gap in
FUTURE data produced a confident false claim about the PRESENT.

So the test that matters is not "does the check pass on good data" -- it is
"does it fail on the exact shape that fooled us".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.validation.franchise_checks import (
    SCHEDULED_GAMES,
    check_regular_season_game_counts,
    check_schedule_is_complete,
)

pytestmark = pytest.mark.integration

SEASON = 2025
FULL_SCHEDULE = SCHEDULED_GAMES[SEASON]


def _two_franchises(conn) -> tuple[int, int]:
    home = conn.execute(
        "INSERT INTO teams (name, abbreviation, is_franchise) "
        "VALUES ('Test Home','THM', TRUE) RETURNING id"
    ).fetchone()[0]
    away = conn.execute(
        "INSERT INTO teams (name, abbreviation, is_franchise) "
        "VALUES ('Test Away','TAW', TRUE) RETURNING id"
    ).fetchone()[0]
    return int(home), int(away)


def _play(conn, home: int, away: int, *, count: int, status: str, start: datetime) -> None:
    for index in range(count):
        conn.execute(
            "INSERT INTO games (season, start_time, home_team_id, away_team_id, status, "
            "season_type, home_score, away_score) "
            "VALUES (%s, %s, %s, %s, %s, 'regular-season', %s, %s)",
            (
                SEASON,
                start + timedelta(days=index),
                home,
                away,
                status,
                80 if status == "final" else None,
                75 if status == "final" else None,
            ),
        )


def test_a_fully_ingested_schedule_passes(clean_db) -> None:
    with clean_db.connection() as conn:
        home, away = _two_franchises(conn)
        _play(conn, home, away, count=FULL_SCHEDULE, status="final",
              start=datetime(SEASON, 5, 1, tzinfo=UTC))
        conn.commit()
        assert check_schedule_is_complete(conn).passed


def test_missing_future_fixtures_are_caught(clean_db) -> None:
    """The exact shape of the real failure: results present, fixtures absent."""
    played = FULL_SCHEDULE - 11
    with clean_db.connection() as conn:
        home, away = _two_franchises(conn)
        _play(conn, home, away, count=played, status="final",
              start=datetime(SEASON, 5, 1, tzinfo=UTC))
        conn.commit()

        result = check_schedule_is_complete(conn)
        assert result.passed is False
        assert result.violation_count == 2  # both franchises
        assert f"only {played} of {FULL_SCHEDULE}" in result.sample_violations[0]


def test_scheduled_games_count_toward_completeness(clean_db) -> None:
    """A known future fixture is knowledge, even though it has not been played.
    Counting only finals would flag every season mid-flight."""
    with clean_db.connection() as conn:
        home, away = _two_franchises(conn)
        _play(conn, home, away, count=FULL_SCHEDULE - 10, status="final",
              start=datetime(SEASON, 5, 1, tzinfo=UTC))
        _play(conn, home, away, count=10, status="scheduled",
              start=datetime(SEASON, 8, 1, tzinfo=UTC))
        conn.commit()
        assert check_schedule_is_complete(conn).passed


def test_the_played_count_check_ignores_a_season_still_in_progress(clean_db) -> None:
    """The two checks ask different questions, and this is the difference: a
    part-played season is complete-as-known but not complete-as-played, and only
    the second is a violation once the season ends."""
    with clean_db.connection() as conn:
        home, away = _two_franchises(conn)
        _play(conn, home, away, count=FULL_SCHEDULE - 10, status="final",
              start=datetime(SEASON, 5, 1, tzinfo=UTC))
        _play(conn, home, away, count=10, status="scheduled",
              start=datetime(SEASON, 8, 1, tzinfo=UTC))
        conn.commit()

        assert check_schedule_is_complete(conn).passed
        assert check_regular_season_game_counts(conn).passed
