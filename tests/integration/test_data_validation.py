"""Integration tests for the data-quality checks in wnba_engine/validation/.

Each check gets a deliberately-bad row (raw SQL, not the normal
ingestion path -- these tests are about the check catching a corrupt
state, not about how that state could arise) and a clean-data case
proving no false positives.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.validation import bounds_checks, consistency_checks, crosswalk_checks
from wnba_engine.validation.runner import run_all_checks

pytestmark = pytest.mark.integration


def _seed_team(conn, name: str, abbreviation: str) -> int:
    row = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES (%s, %s) RETURNING id",
        (name, abbreviation),
    ).fetchone()
    return int(row[0])


def _seed_player(conn, full_name: str) -> int:
    row = conn.execute(
        "INSERT INTO players (full_name, position) VALUES (%s, %s) RETURNING id",
        (full_name, "G"),
    ).fetchone()
    return int(row[0])


def _seed_final_game(conn, home_score: int, away_score: int) -> tuple[int, int, int]:
    home_id = _seed_team(conn, "Home Team", "HME")
    away_id = _seed_team(conn, "Away Team", "AWY")
    row = conn.execute(
        "INSERT INTO games (season, start_time, home_team_id, away_team_id, status, "
        "home_score, away_score) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (2025, datetime(2025, 7, 6, tzinfo=UTC), home_id, away_id, "final", home_score, away_score),
    ).fetchone()
    return home_id, away_id, int(row[0])


def _insert_player_game_stats(conn, *, game_id: int, player_id: int, team_id: int, **stats) -> None:
    columns = ["game_id", "player_id", "team_id", "source", *stats.keys()]
    placeholders = ", ".join(["%s"] * len(columns))
    conn.execute(
        f"INSERT INTO player_game_stats ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
        (game_id, player_id, team_id, "espn", *stats.values()),
    )


def _insert_team_game_stats(conn, *, game_id: int, team_id: int, **stats) -> None:
    columns = ["game_id", "team_id", "source", *stats.keys()]
    placeholders = ", ".join(["%s"] * len(columns))
    conn.execute(
        f"INSERT INTO team_game_stats ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
        (game_id, team_id, "espn", *stats.values()),
    )


_FULL_STAT_LINE = dict(
    field_goals_made=0,
    field_goals_attempted=0,
    three_pointers_made=0,
    three_pointers_attempted=0,
    free_throws_made=0,
    free_throws_attempted=0,
    rebounds=0,
    offensive_rebounds=0,
    defensive_rebounds=0,
    assists=0,
    steals=0,
    blocks=0,
    turnovers=0,
    fouls=0,
)


def test_orphaned_crosswalk_entries_detects_dangling_internal_id(clean_db):
    with clean_db.connection() as conn:
        conn.execute(
            "INSERT INTO provider_entity_map (provider, entity_type, external_id, internal_id) "
            "VALUES (%s, %s, %s, %s)",
            ("espn", "player", "999999", 424242),
        )
        result = crosswalk_checks.check_orphaned_crosswalk_entries(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_orphaned_crosswalk_entries_passes_with_real_reference(clean_db):
    with clean_db.connection() as conn:
        player_id = _seed_player(conn, "Real Player")
        conn.execute(
            "INSERT INTO provider_entity_map (provider, entity_type, external_id, internal_id) "
            "VALUES (%s, %s, %s, %s)",
            ("espn", "player", "1", player_id),
        )
        result = crosswalk_checks.check_orphaned_crosswalk_entries(conn)
    assert result.passed is True
    assert result.violation_count == 0


def test_duplicate_crosswalk_mappings_detects_two_external_ids_one_internal_id(clean_db):
    with clean_db.connection() as conn:
        player_id = _seed_player(conn, "Shared Name")
        conn.execute(
            "INSERT INTO provider_entity_map (provider, entity_type, external_id, internal_id) "
            "VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
            ("balldontlie", "player", "111", player_id, "balldontlie", "player", "222", player_id),
        )
        result = crosswalk_checks.check_duplicate_crosswalk_mappings(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_duplicate_crosswalk_mappings_passes_with_one_to_one_mapping(clean_db):
    with clean_db.connection() as conn:
        player_id = _seed_player(conn, "Unique Player")
        conn.execute(
            "INSERT INTO provider_entity_map (provider, entity_type, external_id, internal_id) "
            "VALUES (%s, %s, %s, %s)",
            ("balldontlie", "player", "111", player_id),
        )
        result = crosswalk_checks.check_duplicate_crosswalk_mappings(conn)
    assert result.passed is True


def test_team_box_score_matches_final_score_detects_mismatch(clean_db):
    with clean_db.connection() as conn:
        home_id, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        player_id = _seed_player(conn, "Home Scorer")
        _insert_player_game_stats(
            conn, game_id=game_id, player_id=player_id, team_id=home_id, points=60
        )
        result = consistency_checks.check_team_box_score_matches_final_score(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_team_box_score_matches_final_score_passes_when_sums_match(clean_db):
    with clean_db.connection() as conn:
        home_id, away_id, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        home_scorer = _seed_player(conn, "Home Scorer")
        away_scorer = _seed_player(conn, "Away Scorer")
        _insert_player_game_stats(
            conn, game_id=game_id, player_id=home_scorer, team_id=home_id, points=70
        )
        _insert_player_game_stats(
            conn, game_id=game_id, player_id=away_scorer, team_id=away_id, points=60
        )
        result = consistency_checks.check_team_box_score_matches_final_score(conn)
    assert result.passed is True


def test_team_totals_match_player_sums_detects_mismatch(clean_db):
    with clean_db.connection() as conn:
        home_id, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        player_id = _seed_player(conn, "Player")
        _insert_team_game_stats(conn, game_id=game_id, team_id=home_id, **_FULL_STAT_LINE)
        conn.execute(
            "UPDATE team_game_stats SET field_goals_made = 30 WHERE game_id = %s", (game_id,)
        )
        _insert_player_game_stats(
            conn,
            game_id=game_id,
            player_id=player_id,
            team_id=home_id,
            **{**_FULL_STAT_LINE, "field_goals_made": 25},
        )
        result = consistency_checks.check_team_totals_match_player_sums(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_team_totals_match_player_sums_passes_when_matching(clean_db):
    with clean_db.connection() as conn:
        home_id, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        player_id = _seed_player(conn, "Player")
        _insert_team_game_stats(conn, game_id=game_id, team_id=home_id, **_FULL_STAT_LINE)
        _insert_player_game_stats(
            conn, game_id=game_id, player_id=player_id, team_id=home_id, **_FULL_STAT_LINE
        )
        result = consistency_checks.check_team_totals_match_player_sums(conn)
    assert result.passed is True


def _insert_play(
    conn,
    *,
    game_id: int,
    sequence: int,
    home_score: int,
    away_score: int,
    play_type: str = "End Game",
) -> None:
    conn.execute(
        "INSERT INTO game_plays (game_id, source, sequence, period, play_type, "
        "home_score, away_score, scoring_play, score_value) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (game_id, "balldontlie", sequence, 4, play_type, home_score, away_score, True, 2),
    )


def test_plays_final_score_matches_game_score_detects_mismatch(clean_db):
    with clean_db.connection() as conn:
        _, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        _insert_play(conn, game_id=game_id, sequence=1, home_score=65, away_score=60)
        result = consistency_checks.check_plays_final_score_matches_game_score(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_plays_final_score_matches_game_score_passes_when_matching(clean_db):
    with clean_db.connection() as conn:
        _, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        _insert_play(conn, game_id=game_id, sequence=1, home_score=70, away_score=60)
        result = consistency_checks.check_plays_final_score_matches_game_score(conn)
    assert result.passed is True


def test_plays_final_score_ignores_non_end_game_rows_with_a_higher_sequence(clean_db):
    """Regression test: balldontlie's "order" field isn't reliably
    monotonic -- verified live that a period-1 jumpball can carry a
    sequence number higher than the real final play. A stray high-sequence
    row with a mismatched score must NOT fail the check as long as the
    "End Game" row's score is correct."""
    with clean_db.connection() as conn:
        _, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        _insert_play(conn, game_id=game_id, sequence=1, home_score=70, away_score=60)
        _insert_play(
            conn,
            game_id=game_id,
            sequence=999,
            home_score=2,
            away_score=0,
            play_type="Jumpball",
        )
        result = consistency_checks.check_plays_final_score_matches_game_score(conn)
    assert result.passed is True


def test_team_stat_bounds_detects_fgm_greater_than_fga(clean_db):
    with clean_db.connection() as conn:
        home_id, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        _insert_team_game_stats(
            conn,
            game_id=game_id,
            team_id=home_id,
            **{**_FULL_STAT_LINE, "field_goals_made": 30, "field_goals_attempted": 20},
        )
        result = bounds_checks.check_team_stat_bounds(conn)
    assert result.passed is False


def test_team_stat_bounds_passes_with_valid_data(clean_db):
    with clean_db.connection() as conn:
        home_id, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        _insert_team_game_stats(
            conn,
            game_id=game_id,
            team_id=home_id,
            **{
                **_FULL_STAT_LINE,
                "field_goals_made": 20,
                "field_goals_attempted": 40,
                "offensive_rebounds": 5,
                "defensive_rebounds": 25,
                "rebounds": 30,
            },
        )
        result = bounds_checks.check_team_stat_bounds(conn)
    assert result.passed is True


def test_player_stat_bounds_detects_oreb_dreb_mismatch(clean_db):
    with clean_db.connection() as conn:
        home_id, _, game_id = _seed_final_game(conn, home_score=70, away_score=60)
        player_id = _seed_player(conn, "Player")
        _insert_player_game_stats(
            conn,
            game_id=game_id,
            player_id=player_id,
            team_id=home_id,
            **{**_FULL_STAT_LINE, "offensive_rebounds": 3, "defensive_rebounds": 4, "rebounds": 10},
        )
        result = bounds_checks.check_player_stat_bounds(conn)
    assert result.passed is False


def test_market_price_bounds_detects_out_of_range_probability(clean_db):
    with clean_db.connection() as conn:
        conn.execute(
            "INSERT INTO market_price_snapshots (provider, market_external_id, title, "
            "status, implied_probability, captured_at) VALUES (%s, %s, %s, %s, %s, %s)",
            ("kalshi", "TEST-1", "Test market", "active", 1.5, datetime.now(UTC)),
        )
        result = bounds_checks.check_market_price_bounds(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_market_price_bounds_passes_with_valid_probability(clean_db):
    with clean_db.connection() as conn:
        conn.execute(
            "INSERT INTO market_price_snapshots (provider, market_external_id, title, "
            "status, implied_probability, captured_at) VALUES (%s, %s, %s, %s, %s, %s)",
            ("kalshi", "TEST-1", "Test market", "active", 0.5, datetime.now(UTC)),
        )
        result = bounds_checks.check_market_price_bounds(conn)
    assert result.passed is True


_ZONE_COLUMNS = (
    "restricted_area_fga",
    "restricted_area_fgm",
    "in_the_paint_non_ra_fga",
    "in_the_paint_non_ra_fgm",
    "mid_range_fga",
    "mid_range_fgm",
    "left_corner_3_fga",
    "left_corner_3_fgm",
    "right_corner_3_fga",
    "right_corner_3_fgm",
    "corner_3_fga",
    "corner_3_fgm",
    "above_the_break_3_fga",
    "above_the_break_3_fgm",
    "backcourt_fga",
    "backcourt_fgm",
)


def test_player_shot_zone_bounds_detects_fgm_greater_than_fga(clean_db):
    with clean_db.connection() as conn:
        player_id = _seed_player(conn, "Shooter")
        columns = ", ".join(("player_id", "season", "season_type", *_ZONE_COLUMNS))
        placeholders = ", ".join(["%s"] * (3 + len(_ZONE_COLUMNS)))
        values = [player_id, 2025, "regular"] + [0] * len(_ZONE_COLUMNS)
        # restricted_area_fga=2, restricted_area_fgm=5 -> impossible
        values[3], values[4] = 2, 5
        conn.execute(
            f"INSERT INTO player_shot_zone_stats ({columns}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        result = bounds_checks.check_player_shot_zone_bounds(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_team_shot_zone_bounds_detects_fgm_greater_than_fga(clean_db):
    with clean_db.connection() as conn:
        team_id = _seed_team(conn, "Zone Team", "ZON")
        columns = ", ".join(("team_id", "season", "season_type", *_ZONE_COLUMNS))
        placeholders = ", ".join(["%s"] * (3 + len(_ZONE_COLUMNS)))
        values = [team_id, 2025, "regular"] + [0] * len(_ZONE_COLUMNS)
        values[3], values[4] = 2, 5
        conn.execute(
            f"INSERT INTO team_shot_zone_stats ({columns}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        result = bounds_checks.check_team_shot_zone_bounds(conn)
    assert result.passed is False
    assert result.violation_count == 1


def test_run_all_checks_returns_a_report_and_passes_on_clean_db(clean_db):
    report = run_all_checks(clean_db)
    assert len(report.checks) == 10
    assert report.passed is True
