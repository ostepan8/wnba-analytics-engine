"""Unit tests for style-as-a-feature.

What these pin is the judgement, not the arithmetic: that a distance is
scaled before it is taken, that "unmeasurable" and "identical" stay
distinguishable, and that mismatched column lists fail at construction
rather than producing a silently wrong number.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame
from wnba_engine.features.steps.style_steps import StyleDistanceStep, StyleVolatilityStep

DIMS = ("pace", "efg")
TEAM = ("pace_mean_5", "efg_mean_5")
OPP = ("opponent_pace_mean_5", "opponent_efg_mean_5")
COLS = ("start_time", *TEAM, *OPP)


def _frame(rows):
    return FeatureFrame.from_rows(rows, columns=COLS).declaring(
        as_of_columns=("start_time",), event_time_column="start_time"
    )


def _ctx():
    return FeatureContext(as_of=datetime(2026, 8, 1, tzinfo=UTC))


def _step():
    return StyleDistanceStep(team_columns=TEAM, opponent_columns=OPP, dimensions=DIMS)


def _row(t, at, pace, efg, opace, oefg):
    return {"start_time": t, "pace_mean_5": pace, "efg_mean_5": efg,
            "opponent_pace_mean_5": opace, "opponent_efg_mean_5": oefg}


T = datetime(2026, 7, 1, tzinfo=UTC)


def test_distance_is_scaled_so_the_biggest_unit_does_not_dominate():
    """pace runs ~80 and efg ~0.50. Unscaled, a one-point efg gap would be
    invisible next to a one-point pace gap, and the 'style distance' would
    be a pace distance."""
    # Both dimensions vary by the same amount IN THEIR OWN UNITS (one SD
    # step per row), but the raw pace gap is ~100x the raw efg gap. After
    # scaling the two must contribute equally.
    rows = [_row(f"a{i}", T, 80 + i, 0.50 + i / 100, 82, 0.52) for i in range(5)]

    out = _step().apply(_frame(rows), _ctx())

    for r in out.rows:
        assert abs(r["pace_gap"]) == pytest.approx(abs(r["efg_gap"]), rel=1e-6)


def test_identical_styles_give_zero_distance():
    rows = [_row(f"a{i}", T, 80 + i, 0.50, 80 + i, 0.50) for i in range(5)]

    out = _step().apply(_frame(rows), _ctx())

    assert all(r["style_distance"] == pytest.approx(0.0) for r in out.rows)


def test_unmeasurable_distance_is_none_not_zero():
    """'We could not measure the mismatch' and 'these teams play
    identically' are opposite claims and must not share a value."""
    rows = [_row(f"a{i}", T, 80 + i, 0.5, 80, 0.5) for i in range(4)]
    rows.append(_row("missing", T, None, None, None, None))

    out = _step().apply(_frame(rows), _ctx())
    missing = [r for r in out.rows if r["start_time"] == "missing"][0]

    assert missing["style_distance"] is None
    assert missing["pace_gap"] is None


def test_gaps_are_signed_so_direction_survives():
    """A faster-than-opponent team and a slower one are different states;
    an absolute gap would collapse them."""
    rows = [_row("fast", T, 90, 0.5, 80, 0.5), _row("slow", T, 70, 0.5, 80, 0.5),
            _row("x", T, 80, 0.5, 80, 0.5), _row("y", T, 85, 0.5, 80, 0.5)]

    out = _step().apply(_frame(rows), _ctx())
    by = {r["start_time"]: r for r in out.rows}

    assert by["fast"]["pace_gap"] > 0
    assert by["slow"]["pace_gap"] < 0


def test_mismatched_column_lists_fail_at_construction():
    with pytest.raises(StepContractError):
        StyleDistanceStep(team_columns=TEAM, opponent_columns=("only_one",), dimensions=DIMS)


def test_volatility_is_zero_when_recent_matches_long_run():
    step = StyleVolatilityStep(short_columns=("s_a",), long_columns=("l_a",))
    frame = FeatureFrame.from_rows(
        [{"start_time": T, "s_a": 5.0, "l_a": 5.0}], columns=("start_time", "s_a", "l_a")
    ).declaring(as_of_columns=("start_time",), event_time_column="start_time")

    out = step.apply(frame, _ctx())

    assert out.rows[0]["style_volatility"] == pytest.approx(0.0)


def test_volatility_rises_as_recent_style_diverges():
    step = StyleVolatilityStep(short_columns=("s_a",), long_columns=("l_a",))
    frame = FeatureFrame.from_rows(
        [{"start_time": T, "s_a": 5.0, "l_a": 5.0}, {"start_time": T, "s_a": 9.0, "l_a": 5.0}],
        columns=("start_time", "s_a", "l_a"),
    ).declaring(as_of_columns=("start_time",), event_time_column="start_time")

    out = step.apply(frame, _ctx())

    assert out.rows[1]["style_volatility"] > out.rows[0]["style_volatility"]


def test_volatility_rejects_mismatched_window_lists():
    with pytest.raises(StepContractError):
        StyleVolatilityStep(short_columns=("a", "b"), long_columns=("a",))
