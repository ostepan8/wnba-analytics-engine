"""Categorical encoding and scaling."""

from __future__ import annotations

from datetime import timedelta

import pytest
from feature_fixtures import FIRST_TIP, TEAM_COLUMNS, context, frame_of, team_row

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps import encoding
from wnba_engine.features.steps.derivation import HomeAwayStep


def _apply(
    *steps: object, rows: list[dict[str, object]], extra_columns: tuple[str, ...] = ()
) -> object:
    return Pipeline(name="t", steps=steps).run(  # type: ignore[arg-type]
        frame_of(rows, TEAM_COLUMNS + extra_columns), context=context()
    )


def _home_away_rows() -> list[dict[str, object]]:
    return [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, is_home=True),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2), is_home=False),
    ]


def test_one_hot_emits_a_column_per_declared_category() -> None:
    frame = _apply(
        HomeAwayStep(),
        encoding.OneHotStep(column="home_away", categories=("home", "away")),
        rows=_home_away_rows(),
    )
    assert frame.rows[0]["home_away_is_home"] is True  # type: ignore[attr-defined]
    assert frame.rows[0]["home_away_is_away"] is False  # type: ignore[attr-defined]
    assert frame.rows[1]["home_away_is_away"] is True  # type: ignore[attr-defined]


def test_one_hot_records_an_unknown_category_rather_than_failing() -> None:
    """A category first seen after the boundary the list was chosen at is
    expected in walk-forward use (a 2026 expansion franchise, a new
    season_type). `_is_other` keeps "all zeros" from being ambiguous
    between unknown and null.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, season_type="post-season"),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2)) | {
            "season_type": None
        },
    ]
    frame = _apply(
        encoding.OneHotStep(column="season_type", categories=("regular-season",)), rows=rows
    )
    assert frame.rows[0]["season_type_is_other"] is True  # type: ignore[attr-defined]
    assert frame.rows[1]["season_type_is_other"] is False  # type: ignore[attr-defined]
    assert frame.rows[1]["season_type_is_regular-season"] is False  # type: ignore[attr-defined]


def test_one_hot_rejects_an_empty_or_duplicated_category_list() -> None:
    with pytest.raises(StepContractError):
        encoding.OneHotStep(column="x", categories=())
    with pytest.raises(StepContractError):
        encoding.OneHotStep(column="x", categories=("a", "a"))


def test_observed_categories_is_a_helper_not_a_step() -> None:
    """There is deliberately no fitted one-hot: discovering categories
    from data makes the output SCHEMA data-dependent, which would defeat
    the guard's declared-columns check and give two boundaries different
    columns.
    """
    frame = _apply(HomeAwayStep(), rows=_home_away_rows())
    assert encoding.observed_categories(frame, "home_away") == ("away", "home")  # type: ignore[arg-type]


def test_explicit_scaling_is_reproducible_across_boundaries() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"rest_days": 4.0},
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2))
        | {"rest_days": 2.0},
    ]
    frame = _apply(
        encoding.ScaleStep(column="rest_days", mean=3.0, stddev=1.0),
        rows=rows,
        extra_columns=("rest_days",),
    )
    assert frame.rows[0]["rest_days_scaled"] == pytest.approx(1.0)  # type: ignore[attr-defined]
    assert frame.rows[1]["rest_days_scaled"] == pytest.approx(-1.0)  # type: ignore[attr-defined]


def test_scaling_preserves_nulls() -> None:
    rows = [team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"rest_days": None}]
    frame = _apply(
        encoding.ScaleStep(column="rest_days", mean=3.0, stddev=1.0),
        rows=rows,
        extra_columns=("rest_days",),
    )
    assert frame.rows[0]["rest_days_scaled"] is None  # type: ignore[attr-defined]


def test_scale_step_rejects_a_zero_stddev() -> None:
    with pytest.raises(StepContractError):
        encoding.ScaleStep(column="x", mean=0.0, stddev=0.0)


def test_fitted_scaling_uses_only_the_frame_it_is_given() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"rest_days": 1.0},
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2))
        | {"rest_days": 3.0},
    ]
    frame = _apply(
        encoding.FitScaleStep(column="rest_days"), rows=rows, extra_columns=("rest_days",)
    )
    assert frame.rows[0]["rest_days_scaled"] == pytest.approx(-1.0)  # type: ignore[attr-defined]
    assert frame.rows[1]["rest_days_scaled"] == pytest.approx(1.0)  # type: ignore[attr-defined]


def test_fitted_scaling_of_a_constant_column_is_zero_not_a_crash() -> None:
    """A degenerate early-season slice should not abort a whole build; a
    constant carries no information and 0.0 says so.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"rest_days": 2.0},
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2))
        | {"rest_days": 2.0},
    ]
    frame = _apply(
        encoding.FitScaleStep(column="rest_days"), rows=rows, extra_columns=("rest_days",)
    )
    assert frame.rows[0]["rest_days_scaled"] == 0.0  # type: ignore[attr-defined]
