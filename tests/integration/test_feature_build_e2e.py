"""Integration tests for the feature layer, against a real Postgres.

These exist because the unit tests drive an in-memory source and
therefore never execute the SQL. Everything that can only be wrong in the
query lives here: the as-of WHERE clauses, the two-rows-per-game lateral
join, the `player_game_stats.source` filter that a naive query silently
doubles, and the guard's check that the column tuple declared in
feature_repo still matches what the SELECT actually returns.

Seeded with raw SQL rather than the ingestion pipelines: the point is a
known, minimal schedule whose correct answers can be written down, not a
realistic ingest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import LeakageError
from wnba_engine.features.source import PostgresRowSource
from wnba_engine.features.steps.loading import DEFAULT_COMPLETION_MARGIN
from wnba_engine.repositories import feature_repo

pytestmark = pytest.mark.integration

SEASON = 2025
TIP_ONE = datetime(2025, 6, 1, 23, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def _seed_team(conn, name: str, abbrev: str, *, is_franchise: bool = True) -> int:
    row = conn.execute(
        "INSERT INTO teams (name, abbreviation, is_franchise) VALUES (%s, %s, %s) RETURNING id",
        (name, abbrev, is_franchise),
    ).fetchone()
    return int(row[0])


def _seed_game(
    conn,
    *,
    home_id: int,
    away_id: int,
    start_time: datetime,
    home_score: int = 90,
    away_score: int = 80,
    status: str = "final",
    season_type: str = "regular-season",
    season: int = SEASON,
) -> int:
    row = conn.execute(
        "INSERT INTO games (season, start_time, home_team_id, away_team_id, status, "
        "home_score, away_score, season_type) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (season, start_time, home_id, away_id, status, home_score, away_score, season_type),
    ).fetchone()
    return int(row[0])


def _seed_schedule(conn) -> dict[str, object]:
    """Two franchises, one national team, four games over eight days."""
    home = _seed_team(conn, "Home Franchise", "HME")
    away = _seed_team(conn, "Away Franchise", "AWY")
    exhibition = _seed_team(conn, "Japan", "JPN", is_franchise=False)

    games = [
        _seed_game(conn, home_id=home, away_id=away, start_time=TIP_ONE, home_score=90,
                   away_score=80),
        _seed_game(conn, home_id=away, away_id=home, start_time=TIP_ONE + DAY, home_score=70,
                   away_score=75),
        _seed_game(conn, home_id=home, away_id=away, start_time=TIP_ONE + 4 * DAY, home_score=88,
                   away_score=99),
        _seed_game(conn, home_id=home, away_id=away, start_time=TIP_ONE + 8 * DAY, home_score=101,
                   away_score=95),
    ]
    # Filtered out by the loader's season_type clause and by FranchiseOnlyStep.
    _seed_game(
        conn,
        home_id=home,
        away_id=exhibition,
        start_time=TIP_ONE + 2 * DAY,
        season_type="preseason",
    )
    conn.commit()
    return {"home": home, "away": away, "exhibition": exhibition, "games": games}


def _context(as_of: datetime) -> FeatureContext:
    return FeatureContext(as_of=as_of, seasons=(SEASON,))


def test_team_games_stop_at_the_as_of_boundary(clean_db) -> None:
    with clean_db.connection() as conn:
        seeded = _seed_schedule(conn)
        after_second = TIP_ONE + 2 * DAY
        rows = feature_repo.load_team_games(
            conn,
            as_of=after_second,
            season_types=("regular-season", "post-season"),
            seasons=(SEASON,),
        )

    game_ids = {row["game_id"] for row in rows}
    assert game_ids == {seeded["games"][0], seeded["games"][1]}  # type: ignore[index]
    assert len(rows) == 4  # two rows per game, one per side


def test_team_games_returns_the_columns_the_step_declares(clean_db) -> None:
    """The guard compares the declaration against what actually arrives,
    so a SELECT that grows a column without updating TEAM_GAME_COLUMNS
    fails the next build. This asserts the pair directly.
    """
    with clean_db.connection() as conn:
        _seed_schedule(conn)
        rows = feature_repo.load_team_games(
            conn,
            as_of=TIP_ONE + 30 * DAY,
            season_types=("regular-season",),
            seasons=(SEASON,),
        )
    assert set(rows[0]) == set(feature_repo.TEAM_GAME_COLUMNS)


def test_preseason_and_non_franchise_games_are_excluded(clean_db) -> None:
    with clean_db.connection() as conn:
        seeded = _seed_schedule(conn)
        rows = feature_repo.load_team_games(
            conn,
            as_of=TIP_ONE + 30 * DAY,
            season_types=("regular-season", "post-season"),
            seasons=(SEASON,),
        )
    assert seeded["exhibition"] not in {row["team_id"] for row in rows}  # type: ignore[operator]


def test_standings_history_is_read_per_row_not_latest_first(clean_db) -> None:
    """The concrete leak this package had: a snapshot captured AFTER a
    game must not be attached to it, even though it precedes as_of.
    """
    with clean_db.connection() as conn:
        seeded = _seed_schedule(conn)
        home = seeded["home"]
        for captured_at, wins in ((TIP_ONE + 2 * DAY, 1), (TIP_ONE + 6 * DAY, 2)):
            conn.execute(
                "INSERT INTO team_standings_history (team_id, season, source, conference, "
                "wins, losses, win_percentage, games_behind, home_record, away_record, "
                "conference_record, playoff_seed, captured_at) VALUES "
                "(%s, %s, 'balldontlie', 'East', %s, 0, 1.0, 0, '1-0', '0-0', '1-0', 1, %s)",
                (home, SEASON, wins, captured_at),
            )
        conn.commit()

        source = PostgresRowSource(conn)
        from wnba_engine.features import strategies
        from wnba_engine.features.steps.loading import JoinStandingsSnapshotStep

        # Standings are not in team_form by default (history starts
        # 2026-07-09), so layer the step back on -- the per-row as-of join
        # is exactly what this test exists to verify.
        frame = strategies.team_form(source).with_steps(
            (JoinStandingsSnapshotStep(source=source),)
        ).run(
            context=_context(TIP_ONE + 30 * DAY)
        )

    by_game = {
        (row["game_id"], row["team_id"]): row for row in frame.rows if row["team_id"] == home
    }
    ordered = [by_game[key] for key in sorted(by_game, key=lambda k: k[0])]
    # game 1 (day 0): no snapshot existed yet
    assert ordered[0]["standings_wins"] is None
    # game 3 (day 4): only the day-2 snapshot precedes it
    assert ordered[2]["standings_wins"] == 1
    # game 4 (day 8): the day-6 snapshot now precedes it
    assert ordered[3]["standings_wins"] == 2


def test_standings_history_is_empty_before_the_first_capture(clean_db) -> None:
    """The real database's earliest captured_at is 2026-07-09, so every
    2022-2025 game legitimately has no standings. Returning nothing is
    the honest answer; back-filling from team_standings would invent it.
    """
    with clean_db.connection() as conn:
        _seed_schedule(conn)
        rows = feature_repo.load_standings_snapshots(
            conn, as_of=TIP_ONE - 30 * DAY, seasons=(SEASON,)
        )
    assert rows == ()


def test_player_games_are_not_doubled_by_the_second_box_score_source(clean_db) -> None:
    """player_game_stats holds ESPN and balldontlie rows for the same
    games (31,096 and 29,237 respectively in the real database). Omitting
    the source filter doubles every player's game count and halves every
    per-game average -- which reads as a modelling problem, not a bug.
    """
    with clean_db.connection() as conn:
        seeded = _seed_schedule(conn)
        player = conn.execute(
            "INSERT INTO players (full_name) VALUES ('Test Player') RETURNING id"
        ).fetchone()[0]
        for source in ("espn", "balldontlie"):
            conn.execute(
                "INSERT INTO player_game_stats (game_id, player_id, team_id, source, minutes, "
                "points, rebounds, assists, three_pointers_made) "
                "VALUES (%s, %s, %s, %s, 30, 20, 5, 4, 2)",
                (seeded["games"][0], player, seeded["home"], source),  # type: ignore[index]
            )
        conn.commit()

        espn_only = feature_repo.load_player_games(
            conn,
            as_of=TIP_ONE + 30 * DAY,
            season_types=("regular-season",),
            seasons=(SEASON,),
            box_score_source="espn",
        )
        both_sources_would_be = conn.execute(
            "SELECT count(*) FROM player_game_stats WHERE player_id = %s", (player,)
        ).fetchone()[0]

    assert len(espn_only) == 1
    assert both_sources_would_be == 2


def test_completion_margin_excludes_a_game_still_in_progress(clean_db) -> None:
    """`games` records when a game STARTED, not when its result became
    known, so a boundary moments after tip-off would otherwise consume a
    final score nobody could have had.
    """
    with clean_db.connection() as conn:
        seeded = _seed_schedule(conn)
        from wnba_engine.features import strategies

        just_after_tip = TIP_ONE + timedelta(minutes=30)
        frame = strategies.situational_baseline(PostgresRowSource(conn)).run(
            context=_context(just_after_tip)
        )
        assert len(frame) == 0

        settled = TIP_ONE + DEFAULT_COMPLETION_MARGIN + timedelta(minutes=1)
        frame = strategies.situational_baseline(PostgresRowSource(conn)).run(
            context=_context(settled)
        )
    assert {row["game_id"] for row in frame.rows} == {seeded["games"][0]}  # type: ignore[index]


def test_full_strategy_runs_guarded_against_real_sql(clean_db) -> None:
    with clean_db.connection() as conn:
        _seed_schedule(conn)
        from wnba_engine.features import strategies

        frame = strategies.team_form(PostgresRowSource(conn)).run(
            context=_context(TIP_ONE + 30 * DAY)
        )

    assert len(frame) == 8  # four regular-season games, two sides each
    assert "points_scored_mean_5" in frame.column_set
    for row in frame.rows:
        window_end = row["rolling_form_5__window_end"]
        assert window_end is None or window_end < row["start_time"]  # type: ignore[operator]


def test_a_pipeline_pointed_past_the_boundary_fails_against_real_data(clean_db) -> None:
    """Belt-and-braces: feed rows loaded at a LATER boundary into a
    context with an earlier one, proving the guard is not merely agreeing
    with the loader's own WHERE clause.
    """
    from wnba_engine.features import strategies
    from wnba_engine.features.source import StaticRowSource

    with clean_db.connection() as conn:
        _seed_schedule(conn)
        rows = feature_repo.load_team_games(
            conn,
            as_of=TIP_ONE + 30 * DAY,
            season_types=("regular-season",),
            seasons=(SEASON,),
        )

    with pytest.raises(LeakageError):
        strategies.situational_baseline(StaticRowSource(team_game_rows=rows)).run(
            context=_context(TIP_ONE + 2 * DAY)
        )
