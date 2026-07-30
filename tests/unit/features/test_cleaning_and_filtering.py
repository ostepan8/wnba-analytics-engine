"""Null policy, type coercion, deduplication, and row filters."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from feature_fixtures import FIRST_TIP, context, frame_of, team_row, team_schedule

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps import cleaning, filtering


def _apply(*steps: object, rows: list[dict[str, object]]) -> object:
    return Pipeline(name="t", steps=steps).run(  # type: ignore[arg-type]
        frame_of(rows), context=context()
    )


def test_decimal_columns_are_coerced_to_float() -> None:
    """psycopg maps NUMERIC to Decimal, and Decimal * float raises
    TypeError -- so an uncoerced `pace` turns the first rolling average
    into a crash rather than a wrong number.
    """
    rows = [team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace=Decimal("98.5"))]
    frame = _apply(
        cleaning.CoerceTypesStep(coercions=(("pace", cleaning.TO_FLOAT),)), rows=rows
    )
    value = frame.rows[0]["pace"]  # type: ignore[attr-defined]
    assert isinstance(value, float)
    assert value == pytest.approx(98.5)


def test_coercion_preserves_nulls() -> None:
    """Coercing a null to 0.0 would erase the distinction the flag/fill
    steps exist to preserve.
    """
    rows = [team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace=None)]
    frame = _apply(
        cleaning.CoerceTypesStep(coercions=(("pace", cleaning.TO_FLOAT),)), rows=rows
    )
    assert frame.rows[0]["pace"] is None  # type: ignore[attr-defined]


def test_coercion_of_an_impossible_value_fails_loudly() -> None:
    rows = [team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace="fast")]  # type: ignore[arg-type]
    with pytest.raises(StepContractError):
        _apply(cleaning.CoerceTypesStep(coercions=(("pace", cleaning.TO_FLOAT),)), rows=rows)


def test_flag_then_fill_keeps_an_imputed_value_distinguishable() -> None:
    """Flag BEFORE filling, or every flag reads False -- the ordering is
    the whole reason these are two steps rather than one.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace=None),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2), pace=99.0),
    ]
    frame = _apply(
        cleaning.FlagNullsStep(columns=("pace",)),
        cleaning.FillNullsStep(policies=cleaning.fill_policies({"pace": 0.0})),
        rows=rows,
    )
    assert frame.rows[0]["pace"] == 0.0  # type: ignore[attr-defined]
    assert frame.rows[0]["pace_is_null"] is True  # type: ignore[attr-defined]
    assert frame.rows[1]["pace_is_null"] is False  # type: ignore[attr-defined]


def test_drop_null_rows_is_a_filter_not_a_transform() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace=None),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2), pace=99.0),
    ]
    frame = _apply(cleaning.DropNullRowsStep(columns=("pace",)), rows=rows)
    assert [row["game_id"] for row in frame.rows] == [2]  # type: ignore[attr-defined]


def test_deduplicate_keeps_the_earliest_row_per_key() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, points_scored=80),
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, points_scored=99),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=1)),
    ]
    frame = _apply(cleaning.DeduplicateStep(key_columns=("game_id", "team_id")), rows=rows)
    assert len(frame) == 2  # type: ignore[arg-type]
    assert frame.rows[0]["points_scored"] == 80  # type: ignore[attr-defined]


def test_franchise_filter_checks_both_sides() -> None:
    """`teams` holds national teams and All-Star roster constructs flagged
    is_franchise = false (migration 0010). A franchise playing Japan is
    still not a WNBA game.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP),
        team_row(
            game_id=2,
            team_id=1,
            start_time=FIRST_TIP + timedelta(days=1),
            opponent_is_franchise=False,
        ),
        team_row(
            game_id=3,
            team_id=2,
            start_time=FIRST_TIP + timedelta(days=2),
            team_is_franchise=False,
        ),
    ]
    frame = _apply(filtering.FranchiseOnlyStep(), rows=rows)
    assert [row["game_id"] for row in frame.rows] == [1]  # type: ignore[attr-defined]


def test_season_type_filter_uses_the_context() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, season_type="regular-season"),
        team_row(
            game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=1), season_type="preseason"
        ),
    ]
    frame = Pipeline(name="t", steps=(filtering.SeasonTypeStep(),)).run(
        frame_of(rows), context=context()
    )
    assert [row["game_id"] for row in frame.rows] == [1]


def test_seasons_filter_is_a_no_op_when_the_context_names_none() -> None:
    rows = team_schedule(count=2)
    frame = Pipeline(name="t", steps=(filtering.SeasonsStep(),)).run(
        frame_of(rows), context=context(seasons=())
    )
    assert len(frame) == 2


def test_minimum_minutes_drops_null_minutes() -> None:
    """player_game_stats stores NULL minutes for a DNP (migration 0002),
    so null means "did not appear", not "unrecorded".
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"minutes": None},
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=1)) | {"minutes": 3},
        team_row(game_id=3, team_id=1, start_time=FIRST_TIP + timedelta(days=2)) | {"minutes": 25},
    ]
    frame = _apply(filtering.MinimumMinutesStep(minimum=5), rows=rows)
    assert [row["game_id"] for row in frame.rows] == [3]  # type: ignore[attr-defined]


def test_minimum_prior_games_drops_rows_with_no_history() -> None:
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"season_games_prior": 0},
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=1))
        | {"season_games_prior": 5},
    ]
    frame = _apply(filtering.MinimumPriorGamesStep(minimum=3), rows=rows)
    assert [row["game_id"] for row in frame.rows] == [2]  # type: ignore[attr-defined]
