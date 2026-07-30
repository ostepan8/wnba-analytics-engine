"""Unit tests for opponent mirroring.

The gap this closes: the team-game frame carried `opponent_team_id` and
derived nothing from it, so a model on that frame saw one half of every
matchup.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame
from wnba_engine.features.steps.derivation import OpponentFormStep

TIP = datetime(2026, 6, 1, 23, 0, tzinfo=UTC)
EARLIER = datetime(2026, 5, 30, 23, 0, tzinfo=UTC)


def _frame(rows):
    columns = ("game_id", "team_id", "opponent_team_id", "start_time", "form", "win_end")
    return FeatureFrame.from_rows(rows, columns=columns).declaring(
        as_of_columns=("start_time",), event_time_column="start_time"
    )


def _context():
    return FeatureContext(as_of=datetime(2026, 7, 1, tzinfo=UTC))


def _pair():
    return [
        {"game_id": 1, "team_id": 10, "opponent_team_id": 20, "start_time": TIP,
         "form": 88.0, "win_end": EARLIER},
        {"game_id": 1, "team_id": 20, "opponent_team_id": 10, "start_time": TIP,
         "form": 75.0, "win_end": EARLIER},
    ]


def _step():
    return OpponentFormStep(
        value_columns=("form",), source_window_end_column="win_end", label="opp"
    )


def test_each_row_gets_its_opponents_value_not_its_own():
    frame = _step().apply(_frame(_pair()), _context())
    rows = sorted(frame.rows, key=lambda r: r["team_id"])

    assert rows[0]["opponent_form"] == 75.0  # team 10 sees team 20's form
    assert rows[1]["opponent_form"] == 88.0  # and vice versa


def test_window_end_is_inherited_so_the_guard_can_check_it():
    """The mirrored value is only as fresh as the opponent's own window,
    and the guard compares that against this row's tip-off."""
    frame = _step().apply(_frame(_pair()), _context())

    assert all(row["opp__window_end"] == EARLIER for row in frame.rows)


def test_a_missing_opponent_row_yields_null_not_an_invented_value():
    """The opponent may have been filtered out (a non-franchise
    exhibition side). Nulls are honest; a default would be a fabrication."""
    rows = _pair()[:1]  # drop the sibling

    frame = _step().apply(_frame(rows), _context())

    assert frame.rows[0]["opponent_form"] is None
    assert frame.rows[0]["opp__window_end"] is None


def test_mirroring_a_column_that_does_not_exist_is_a_contract_error():
    """Ordering matters -- this must run after the rolling step whose
    columns it mirrors, and getting that wrong must fail loudly."""
    step = OpponentFormStep(
        value_columns=("never_computed",), source_window_end_column="win_end", label="opp"
    )

    with pytest.raises(StepContractError):
        step.apply(_frame(_pair()), _context())


def test_at_least_one_value_column_is_required():
    with pytest.raises(StepContractError):
        OpponentFormStep(value_columns=(), source_window_end_column="win_end")
