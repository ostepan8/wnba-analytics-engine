"""Player rates and role: the numbers.

The single most important test in this file is
`test_a_ratio_of_sums_is_not_a_mean_of_ratios`. MODELING_FINDINGS.md
records that getting it wrong scored MAE 8.0045 against a 3.05 baseline
-- a 2.6x regression from one line of arithmetic -- so the distinction is
asserted directly rather than trusted to the implementation reading
correctly.

Leakage properties live in test_leakage_guard.py, including the
simultaneous-row case a real row in this database exposed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from feature_fixtures import FIRST_TIP, context

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps.player_steps import (
    PER_36,
    RollingRateStep,
    RollingShareStep,
    RollingWeightedMeanStep,
    team_minutes_played,
)

PLAYER_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "start_time",
    "player_id",
    "team_id",
    "minutes",
    "points",
    "field_goals_attempted",
    "three_pointers_attempted",
    "usage_pct",
)


def player_row(
    *,
    game_id: int,
    player_id: int = 7,
    team_id: int = 1,
    start_time,
    minutes: float | None = 30.0,
    points: float | None = 15.0,
    fga: float | None = 12.0,
    tpa: float | None = 4.0,
    usage: float | None = 0.20,
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "season": 2025,
        "start_time": start_time,
        "player_id": player_id,
        "team_id": team_id,
        "minutes": minutes,
        "points": points,
        "field_goals_attempted": fga,
        "three_pointers_attempted": tpa,
        "usage_pct": usage,
    }


def _frame(rows: list[dict[str, object]]) -> FeatureFrame:
    return FeatureFrame.from_rows(
        rows,
        columns=PLAYER_COLUMNS,
        as_of_columns=("start_time",),
        event_time_column="start_time",
    )


def _apply(*steps: object, rows: list[dict[str, object]]) -> object:
    return Pipeline(name="t", steps=steps).run(  # type: ignore[arg-type]
        _frame(rows), context=context()
    )


# -- the finding this module exists to encode ---------------------------


def test_a_ratio_of_sums_is_not_a_mean_of_ratios() -> None:
    """A 3-minute cameo scoring 3 and a 40-minute start scoring 20.

    Ratio of sums: 36 * 23 / 43 = 19.26 points per 36.
    Mean of ratios: (36*3/3 + 36*20/40) / 2 = (36 + 18) / 2 = 27.0.

    The second is 40% higher, and it is higher for exactly the reason
    MODELING_FINDINGS.md gives -- the cameo's noisy 36-per-36 gets the
    same weight as the start's 18. This test pins the correct one and
    would fail loudly if anyone "simplified" the step into a mean.
    """
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, minutes=3, points=3),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), minutes=40, points=20),
        player_row(game_id=3, start_time=FIRST_TIP + timedelta(days=4)),
    ]
    frame = _apply(
        RollingRateStep(
            value_columns=("points",), denominator_column="minutes", window=10
        ),
        rows=rows,
    )
    assert frame.rows[2]["points_per36_10"] == pytest.approx(PER_36 * 23 / 43)  # type: ignore[attr-defined]
    assert frame.rows[2]["points_per36_10"] != pytest.approx(27.0)  # type: ignore[attr-defined]


def test_rate_excludes_the_current_game() -> None:
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, minutes=36, points=36),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), minutes=36, points=0),
    ]
    frame = _apply(
        RollingRateStep(value_columns=("points",), denominator_column="minutes", window=10),
        rows=rows,
    )
    assert frame.rows[0]["points_per36_10"] is None  # type: ignore[attr-defined]
    # The second row sees only the first: 36 points in 36 minutes.
    assert frame.rows[1]["points_per36_10"] == pytest.approx(36.0)  # type: ignore[attr-defined]


def test_a_null_on_either_side_drops_the_observation_from_both_sums() -> None:
    """A DNP stores NULL minutes (db/migrations/0002_box_scores.sql).
    Keeping its points while dropping its minutes would inflate the rate
    by points the denominator never accounted for.
    """
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, minutes=None, points=9),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), minutes=36, points=18),
        player_row(game_id=3, start_time=FIRST_TIP + timedelta(days=4)),
    ]
    frame = _apply(
        RollingRateStep(value_columns=("points",), denominator_column="minutes", window=10),
        rows=rows,
    )
    assert frame.rows[2]["points_per36_10"] == pytest.approx(18.0)  # type: ignore[attr-defined]
    assert frame.rows[2]["rolling_rate__window_games"] == 1  # type: ignore[attr-defined]


def test_a_zero_denominator_across_the_window_is_null_not_zero() -> None:
    """A player with no field-goal attempts has no three-point share.
    Reporting 0.0 would say they took only twos.
    """
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, fga=0, tpa=0),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2)),
    ]
    frame = _apply(
        RollingRateStep(
            value_columns=("three_pointers_attempted",),
            denominator_column="field_goals_attempted",
            window=10,
            scale=1.0,
            suffix="share_of_fga",
        ),
        rows=rows,
    )
    assert frame.rows[1]["three_pointers_attempted_share_of_fga_10"] is None  # type: ignore[attr-defined]


def test_a_share_is_the_same_step_at_scale_one() -> None:
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, fga=10, tpa=4),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), fga=10, tpa=6),
        player_row(game_id=3, start_time=FIRST_TIP + timedelta(days=4)),
    ]
    frame = _apply(
        RollingRateStep(
            value_columns=("three_pointers_attempted",),
            denominator_column="field_goals_attempted",
            window=10,
            scale=1.0,
            suffix="share_of_fga",
        ),
        rows=rows,
    )
    # 10 threes on 20 attempts.
    assert frame.rows[2]["three_pointers_attempted_share_of_fga_10"] == pytest.approx(0.5)  # type: ignore[attr-defined]


def test_the_window_count_comes_from_the_denominator() -> None:
    """A step emitting several numerators over one denominator publishes
    ONE count, so it has to be the denominator's -- otherwise the number
    would depend on the order of value_columns.
    """
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, minutes=20, points=None),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), minutes=20, points=10),
        player_row(game_id=3, start_time=FIRST_TIP + timedelta(days=4)),
    ]
    frame = _apply(
        RollingRateStep(value_columns=("points",), denominator_column="minutes", window=10),
        rows=rows,
    )
    assert frame.rows[2]["rolling_rate__window_games"] == 2  # type: ignore[attr-defined]


def test_rate_step_rejects_a_nonsense_configuration() -> None:
    with pytest.raises(StepContractError):
        RollingRateStep(value_columns=("points",), denominator_column="minutes", window=0)
    with pytest.raises(StepContractError):
        RollingRateStep(value_columns=(), denominator_column="minutes", window=5)
    with pytest.raises(StepContractError):
        RollingRateStep(
            value_columns=("points",), denominator_column="minutes", window=5, suffix=""
        )


# -- minutes-weighted means ---------------------------------------------


def test_weighted_mean_weights_by_minutes_and_differs_from_a_plain_mean() -> None:
    """A 4-minute appearance at 40% usage and a 36-minute start at 20%.

    Plain mean: 0.30. Minutes-weighted: (4*0.40 + 36*0.20) / 40 = 0.22.
    The difference is the whole reason this step exists.
    """
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, minutes=4, usage=0.40),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), minutes=36, usage=0.20),
        player_row(game_id=3, start_time=FIRST_TIP + timedelta(days=4)),
    ]
    frame = _apply(
        RollingWeightedMeanStep(
            value_columns=("usage_pct",), weight_column="minutes", window=10
        ),
        rows=rows,
    )
    assert frame.rows[2]["usage_pct_wmean_10"] == pytest.approx(0.22)  # type: ignore[attr-defined]
    assert frame.rows[2]["usage_pct_wmean_10"] != pytest.approx(0.30)  # type: ignore[attr-defined]


def test_weighted_mean_skips_a_zero_or_null_weight() -> None:
    """Arithmetically identical to counting it at weight zero, and only
    the skip is visible in the window count.
    """
    rows = [
        player_row(game_id=1, start_time=FIRST_TIP, minutes=0, usage=0.99),
        player_row(game_id=2, start_time=FIRST_TIP + timedelta(days=2), minutes=None, usage=0.99),
        player_row(game_id=3, start_time=FIRST_TIP + timedelta(days=4), minutes=30, usage=0.25),
        player_row(game_id=4, start_time=FIRST_TIP + timedelta(days=6)),
    ]
    frame = _apply(
        RollingWeightedMeanStep(
            value_columns=("usage_pct",), weight_column="minutes", window=10
        ),
        rows=rows,
    )
    assert frame.rows[3]["usage_pct_wmean_10"] == pytest.approx(0.25)  # type: ignore[attr-defined]
    assert frame.rows[3]["weighted__window_games"] == 1  # type: ignore[attr-defined]


def test_weighted_mean_is_null_with_no_usable_history() -> None:
    rows = [player_row(game_id=1, start_time=FIRST_TIP)]
    frame = _apply(
        RollingWeightedMeanStep(
            value_columns=("usage_pct",), weight_column="minutes", window=10
        ),
        rows=rows,
    )
    assert frame.rows[0]["usage_pct_wmean_10"] is None  # type: ignore[attr-defined]


# -- role: share of the team --------------------------------------------


def _rotation(game_id: int, at, minutes: dict[int, float | None]) -> list[dict[str, object]]:
    """One team's rotation for one game: player_id -> minutes."""
    return [
        player_row(game_id=game_id, player_id=pid, start_time=at, minutes=value)
        for pid, value in minutes.items()
    ]


def test_minutes_share_is_a_ratio_of_sums_over_prior_games() -> None:
    """Player 1 plays 30 of the team's 40 minutes, then 20 of 40.

    Ratio of sums: 50 / 80 = 0.625. A mean of per-game shares would give
    (0.75 + 0.50) / 2 = 0.625 here by coincidence of equal totals, so the
    next test breaks the tie deliberately.
    """
    rows = [
        *_rotation(1, FIRST_TIP, {1: 30, 2: 10}),
        *_rotation(2, FIRST_TIP + timedelta(days=2), {1: 20, 2: 20}),
        *_rotation(3, FIRST_TIP + timedelta(days=4), {1: 25, 2: 15}),
    ]
    frame = _apply(RollingShareStep(value_column="minutes", window=10), rows=rows)
    third = [row for row in frame.rows if row["game_id"] == 3 and row["player_id"] == 1]  # type: ignore[attr-defined]
    assert third[0]["minutes_share_10"] == pytest.approx(50 / 80)


def test_minutes_share_uses_summed_team_totals_not_averaged_shares() -> None:
    """Game 1 is a short-rotation game (team total 40), game 2 a
    long-rotation one (team total 100).

    Ratio of sums: (30 + 20) / (40 + 100) = 0.357.
    Mean of per-game shares: (30/40 + 20/100) / 2 = 0.475.
    """
    rows = [
        *_rotation(1, FIRST_TIP, {1: 30, 2: 10}),
        *_rotation(2, FIRST_TIP + timedelta(days=2), {1: 20, 2: 30, 3: 25, 4: 25}),
        *_rotation(3, FIRST_TIP + timedelta(days=4), {1: 25, 2: 15}),
    ]
    frame = _apply(RollingShareStep(value_column="minutes", window=10), rows=rows)
    third = [row for row in frame.rows if row["game_id"] == 3 and row["player_id"] == 1]  # type: ignore[attr-defined]
    assert third[0]["minutes_share_10"] == pytest.approx(50 / 140)
    assert third[0]["minutes_share_10"] != pytest.approx(0.475)


def test_minutes_share_excludes_the_current_game() -> None:
    """The current game's share would need tonight's rotation, which is
    the thing a role feature exists to stand in for.
    """
    rows = _rotation(1, FIRST_TIP, {1: 30, 2: 10})
    frame = _apply(RollingShareStep(value_column="minutes", window=10), rows=rows)
    assert all(row["minutes_share_10"] is None for row in frame.rows)  # type: ignore[attr-defined]


def test_minutes_share_follows_a_player_across_teams() -> None:
    """A traded player's history carries each game's OWN team total, so
    the share describes the role they had at the time.
    """
    rows = [
        *_rotation(1, FIRST_TIP, {1: 10, 2: 30}),  # team 1, bench role
        # Same player on team 2, a bigger role, with a different total.
        player_row(game_id=2, player_id=1, team_id=2,
                   start_time=FIRST_TIP + timedelta(days=2), minutes=30),
        player_row(game_id=2, player_id=3, team_id=2,
                   start_time=FIRST_TIP + timedelta(days=2), minutes=10),
        player_row(game_id=3, player_id=1, team_id=2,
                   start_time=FIRST_TIP + timedelta(days=4), minutes=30),
    ]
    frame = _apply(RollingShareStep(value_column="minutes", window=10), rows=rows)
    third = [row for row in frame.rows if row["game_id"] == 3]  # type: ignore[attr-defined]
    # 10 of 40 on team 1, then 30 of 40 on team 2 -> 40 of 80.
    assert third[0]["minutes_share_10"] == pytest.approx(0.5)


def test_minutes_share_honours_its_window() -> None:
    rows = [
        *_rotation(1, FIRST_TIP, {1: 40, 2: 0}),
        *_rotation(2, FIRST_TIP + timedelta(days=2), {1: 10, 2: 30}),
        *_rotation(3, FIRST_TIP + timedelta(days=4), {1: 25, 2: 15}),
    ]
    frame = _apply(
        RollingShareStep(value_column="minutes", window=1), rows=rows
    )
    third = [row for row in frame.rows if row["game_id"] == 3 and row["player_id"] == 1]  # type: ignore[attr-defined]
    # window=1 keeps only game 2: 10 of the team's 40 minutes.
    assert third[0]["minutes_share_1"] == pytest.approx(0.25)


def test_share_step_rejects_a_nonsense_window() -> None:
    with pytest.raises(StepContractError):
        RollingShareStep(value_column="minutes", window=0)


# -- the diagnostic helper ----------------------------------------------


def test_team_minutes_played_totals_a_rotation() -> None:
    """The one-line check that a box-score source filter has not gone
    missing: a real team-game should total ~200 player-minutes.
    """
    frame = _frame(_rotation(1, FIRST_TIP, {1: 30, 2: 10}))
    assert team_minutes_played(frame) == {(1, 1): 40.0}
