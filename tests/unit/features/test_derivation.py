"""Situational feature correctness: rest, back-to-backs, rolling form,
season-to-date.

The leakage properties of these steps are asserted in
test_leakage_guard.py; this file is about the numbers being right.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from feature_fixtures import FIRST_TIP, context, frame_of, team_row, team_schedule

from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps.derivation import (
    GameOutcomeStep,
    HomeAwayStep,
    RestDaysStep,
    RollingMeanStep,
    SeasonToDateStep,
)


def _apply(*steps: object, rows: list[dict[str, object]]) -> object:
    return Pipeline(name="t", steps=steps).run(  # type: ignore[arg-type]
        frame_of(rows), context=context()
    )


def test_rest_days_is_null_for_a_teams_first_game() -> None:
    frame = _apply(RestDaysStep(), rows=team_schedule(count=3))
    assert frame.rows[0]["rest_days"] is None  # type: ignore[attr-defined]
    assert frame.rows[0]["is_back_to_back"] is False  # type: ignore[attr-defined]


def test_rest_days_measures_elapsed_time_between_tip_offs() -> None:
    frame = _apply(RestDaysStep(), rows=team_schedule(count=3, gap=timedelta(days=3)))
    assert frame.rows[1]["rest_days"] == pytest.approx(3.0)  # type: ignore[attr-defined]


def test_back_to_back_uses_elapsed_hours_not_utc_dates() -> None:
    """A 21:00 ET tip-off is 01:00 UTC the NEXT day, so consecutive
    evening games can land on UTC dates two apart. Elapsed hours is
    immune to that; a date-difference rule would not be.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(hours=25)),
    ]
    frame = _apply(RestDaysStep(), rows=rows)
    assert frame.rows[1]["is_back_to_back"] is True  # type: ignore[attr-defined]

    spaced = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(hours=48)),
    ]
    frame = _apply(RestDaysStep(), rows=spaced)
    assert frame.rows[1]["is_back_to_back"] is False  # type: ignore[attr-defined]


def test_rest_is_per_group_not_global() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP),
        team_row(game_id=1, team_id=2, start_time=FIRST_TIP),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2)),
    ]
    frame = _apply(RestDaysStep(), rows=rows)
    by_key = {(row["game_id"], row["team_id"]): row for row in frame.rows}  # type: ignore[attr-defined]
    assert by_key[(1, 2)]["rest_days"] is None
    assert by_key[(2, 1)]["rest_days"] == pytest.approx(2.0)


def test_sibling_rows_of_the_same_game_share_the_previous_game() -> None:
    """A player-grain frame has ~12 rows per (team, tip-off). Treating a
    sibling as "the previous game" would report zero rest and publish a
    window end equal to the row's own tip-off.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2)),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2)),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2)),
    ]
    frame = _apply(RestDaysStep(), rows=rows)
    for row in frame.rows[1:]:  # type: ignore[attr-defined]
        assert row["rest_days"] == pytest.approx(2.0)
        assert row["rest_days__window_end"] == FIRST_TIP


def test_rolling_mean_excludes_the_current_row() -> None:
    rows = team_schedule(count=4, scores=[10, 20, 30, 40])
    frame = _apply(
        RollingMeanStep(value_columns=("points_scored",), window=3, label="form"), rows=rows
    )
    means = [row["points_scored_mean_3"] for row in frame.rows]  # type: ignore[attr-defined]
    assert means[0] is None
    assert means[1] == pytest.approx(10.0)
    assert means[2] == pytest.approx(15.0)
    assert means[3] == pytest.approx(20.0)


def test_rolling_mean_honours_the_window_length() -> None:
    rows = team_schedule(count=5, scores=[10, 20, 30, 40, 50])
    frame = _apply(
        RollingMeanStep(value_columns=("points_scored",), window=2, label="form"), rows=rows
    )
    # last two BEFORE the 5th game: 30 and 40
    assert frame.rows[4]["points_scored_mean_2"] == pytest.approx(35.0)  # type: ignore[attr-defined]
    assert frame.rows[4]["form__window_games"] == 2  # type: ignore[attr-defined]


def test_rolling_mean_skips_nulls_and_reports_the_real_contribution() -> None:
    """`pace` is null for any game with no balldontlie advanced-stats row.
    Treating that as zero would drag every average toward nothing.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace=None),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2), pace=100.0),
        team_row(game_id=3, team_id=1, start_time=FIRST_TIP + timedelta(days=4), pace=None),
    ]
    frame = _apply(
        RollingMeanStep(value_columns=("pace",), window=5, label="p"), rows=rows
    )
    assert frame.rows[1]["pace_mean_5"] is None  # type: ignore[attr-defined]
    assert frame.rows[2]["pace_mean_5"] == pytest.approx(100.0)  # type: ignore[attr-defined]
    assert frame.rows[2]["p__window_games"] == 2  # type: ignore[attr-defined]


def test_rolling_mean_sorts_by_event_time_not_row_order() -> None:
    """A strategy is free to insert a step that reorders rows; a window
    fed out-of-order rows would average future games with nothing looking
    wrong at the call site.
    """
    ordered = team_schedule(count=3, scores=[10, 20, 30])
    shuffled = [ordered[2], ordered[0], ordered[1]]
    frame = _apply(
        RollingMeanStep(value_columns=("points_scored",), window=5, label="form"),
        rows=shuffled,
    )
    by_game = {row["game_id"]: row for row in frame.rows}  # type: ignore[attr-defined]
    assert by_game[1]["points_scored_mean_5"] is None
    assert by_game[3]["points_scored_mean_5"] == pytest.approx(15.0)


def test_season_to_date_excludes_the_current_game() -> None:
    rows = team_schedule(count=3, scores=[100, 60, 100])
    for row in rows:
        row["points_allowed"] = 80
    frame = _apply(GameOutcomeStep(), SeasonToDateStep(), rows=rows)
    prior = [row["season_games_prior"] for row in frame.rows]  # type: ignore[attr-defined]
    wins = [row["season_wins_prior"] for row in frame.rows]  # type: ignore[attr-defined]
    assert prior == [0, 1, 2]
    assert wins == [0, 1, 1]
    assert frame.rows[0]["season_win_pct_prior"] is None  # type: ignore[attr-defined]
    assert frame.rows[2]["season_win_pct_prior"] == pytest.approx(0.5)  # type: ignore[attr-defined]


def test_season_to_date_resets_across_seasons() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, season=2024),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2), season=2024),
        team_row(game_id=3, team_id=1, start_time=FIRST_TIP + timedelta(days=4), season=2025),
    ]
    frame = _apply(GameOutcomeStep(), SeasonToDateStep(), rows=rows)
    assert [row["season_games_prior"] for row in frame.rows] == [0, 1, 0]  # type: ignore[attr-defined]


def test_home_away_label_and_outcome() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, is_home=False,
                 points_scored=70, points_allowed=90),
    ]
    frame = _apply(HomeAwayStep(), GameOutcomeStep(), rows=rows)
    assert frame.rows[0]["home_away"] == "away"  # type: ignore[attr-defined]
    assert frame.rows[0]["point_margin"] == -20  # type: ignore[attr-defined]
    assert frame.rows[0]["won"] is False  # type: ignore[attr-defined]


def test_rolling_step_rejects_a_nonsense_window() -> None:
    from wnba_engine.features.errors import StepContractError

    with pytest.raises(StepContractError):
        RollingMeanStep(value_columns=("points_scored",), window=0)
    with pytest.raises(StepContractError):
        RollingMeanStep(value_columns=(), window=3)
