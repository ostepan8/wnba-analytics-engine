"""Pipeline composition -- the "swap a preprocessing class" requirement.

Every mutator must return a NEW Pipeline. If it did not, adapting a
strategy at one call site would silently change it for every other caller
of the same factory, which is the exact failure the immutability rule in
AGENTS.md exists to prevent.
"""

from __future__ import annotations

import pytest
from feature_fixtures import context, frame_of, team_schedule

from wnba_engine.features.errors import FeatureError
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps.derivation import HomeAwayStep, RestDaysStep, RollingMeanStep
from wnba_engine.features.steps.filtering import FranchiseOnlyStep


def _pipeline() -> Pipeline:
    return Pipeline(
        name="base",
        steps=(FranchiseOnlyStep(), HomeAwayStep(), RestDaysStep()),
    )


def test_with_step_does_not_touch_the_original() -> None:
    base = _pipeline()
    extended = base.with_step(RollingMeanStep(value_columns=("points_scored",), window=3))

    assert base.step_names == ("franchise_only", "home_away", "rest_days")
    assert extended.step_names[-1] == "rolling"
    assert base is not extended


def test_without_removes_one_step_and_returns_a_new_pipeline() -> None:
    base = _pipeline()
    trimmed = base.without("home_away")

    assert trimmed.step_names == ("franchise_only", "rest_days")
    assert base.step_names == ("franchise_only", "home_away", "rest_days")


def test_replace_step_keeps_the_position() -> None:
    """Order is semantic here -- a filter moved after a windowed step
    changes what the window saw -- so a swap must not reshuffle.
    """
    base = _pipeline()
    swapped = base.replace_step("rest_days", RestDaysStep(group_by=("player_id",)))

    assert swapped.step_names == base.step_names
    assert swapped.steps[2].group_by == ("player_id",)  # type: ignore[attr-defined]
    assert base.steps[2].group_by == ("team_id",)  # type: ignore[attr-defined]


def test_insert_after_places_a_step_mid_pipeline() -> None:
    base = _pipeline()
    inserted = base.insert_after(
        "franchise_only", RollingMeanStep(value_columns=("points_scored",), window=3)
    )
    assert inserted.step_names == ("franchise_only", "rolling", "home_away", "rest_days")


def test_duplicate_step_names_are_rejected() -> None:
    """Names are the handle without()/replace_step() address; two steps
    sharing one makes both ambiguous.
    """
    with pytest.raises(FeatureError):
        Pipeline(name="dupes", steps=(HomeAwayStep(), HomeAwayStep()))


def test_addressing_an_unknown_step_lists_the_real_ones() -> None:
    with pytest.raises(FeatureError) as excinfo:
        _pipeline().without("nope")
    assert "home_away" in str(excinfo.value)


def test_run_folds_steps_in_order() -> None:
    frame = _pipeline().run(frame_of(team_schedule(count=3)), context=context())
    assert "home_away" in frame.column_set
    assert "rest_days" in frame.column_set
    assert frame.rows[0]["home_away"] == "home"


def test_run_starts_from_an_empty_frame_by_default() -> None:
    """A strategy whose first step is a loader should not need the caller
    to hand it a placeholder frame.
    """
    empty = Pipeline(name="nothing", steps=()).run(context=context())
    assert len(empty) == 0
