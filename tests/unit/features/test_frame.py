"""FeatureFrame: immutability and the projection rules that keep the
guard able to see what it is checking.
"""

from __future__ import annotations

import pytest
from feature_fixtures import FIRST_TIP, TEAM_COLUMNS, frame_of, team_row, team_schedule

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame


def test_rows_cannot_be_mutated_in_place() -> None:
    """Enforced by MappingProxyType, not by convention: a step writing
    back into a row it was handed would corrupt it for every later step,
    and the type annotation alone would not stop it.
    """
    frame = frame_of(team_schedule(count=2))
    with pytest.raises(TypeError):
        frame.rows[0]["points_scored"] = 999  # type: ignore[index]


def test_with_column_returns_a_new_frame_and_leaves_the_original_alone() -> None:
    original = frame_of(team_schedule(count=3))
    extended = original.with_column("doubled", [1, 2, 3])

    assert "doubled" not in original.column_set
    assert extended.columns == (*TEAM_COLUMNS, "doubled")
    assert [row["doubled"] for row in extended.rows] == [1, 2, 3]
    assert len(original.rows[0]) == len(TEAM_COLUMNS)


def test_merge_cells_rejects_a_length_mismatch() -> None:
    """Positional alignment is load-bearing -- a short cell list would
    shift every later row's features onto the wrong game.
    """
    frame = frame_of(team_schedule(count=3))
    with pytest.raises(StepContractError):
        frame.merge_cells(({"x": 1},), ("x",))


def test_declaring_is_additive() -> None:
    """A step must not be able to clear another step's anchor -- dropping
    the declaration is how leaky data would be laundered.
    """
    frame = frame_of(team_schedule(count=1)).declaring(as_of_columns=("pace",))
    assert frame.as_of_columns == frozenset({"start_time", "pace"})


def test_select_refuses_to_drop_an_as_of_anchor() -> None:
    frame = frame_of(team_schedule(count=2))
    with pytest.raises(StepContractError) as excinfo:
        frame.select(["game_id", "points_scored"])
    assert "start_time" in str(excinfo.value)


def test_select_keeps_anchors_and_prunes_the_rest() -> None:
    frame = frame_of(team_schedule(count=2))
    projected = frame.select(["game_id", "start_time", "points_scored"])
    assert projected.columns == ("game_id", "start_time", "points_scored")
    assert set(projected.rows[0]) == {"game_id", "start_time", "points_scored"}


def test_select_rejects_unknown_columns() -> None:
    with pytest.raises(StepContractError):
        frame_of(team_schedule(count=1)).select(["start_time", "not_a_column"])


def test_to_columns_is_the_pandas_bridge() -> None:
    """One dict of lists -- `pd.DataFrame(frame.to_columns())` -- so the
    ML dependency decision ROADMAP.md defers stays cheap to make later.
    """
    frame = frame_of(team_schedule(count=3))
    columns = frame.to_columns()
    assert set(columns) == set(TEAM_COLUMNS)
    assert columns["points_scored"] == [80, 81, 82]
    assert all(len(values) == 3 for values in columns.values())


def test_filter_rows_preserves_declarations() -> None:
    frame = frame_of(team_schedule(count=4))
    kept = frame.filter_rows(lambda row: row["game_id"] in {1, 3})
    assert len(kept) == 2
    assert kept.as_of_columns == frame.as_of_columns
    assert kept.event_time_column == frame.event_time_column


def test_from_rows_uses_declared_columns_not_the_first_row() -> None:
    """A source that omits a null column on some rows must not be able to
    change the frame's schema by row order -- the guard's "added exactly
    what was declared" check would start passing or failing at random.
    """
    frame = FeatureFrame.from_rows(
        [team_row(game_id=1, team_id=1, start_time=FIRST_TIP)],
        columns=(*TEAM_COLUMNS, "never_present"),
        as_of_columns=("start_time",),
        event_time_column="start_time",
    )
    assert "never_present" in frame.column_set
    assert frame.to_columns()["never_present"] == [None]


def test_empty_frame_is_the_pipeline_starting_point() -> None:
    empty = FeatureFrame.empty()
    assert len(empty) == 0
    assert empty.columns == ()
    assert empty.event_time_column is None
