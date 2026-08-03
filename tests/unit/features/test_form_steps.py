"""Multi-window team form: the numbers.

The leakage properties of these steps are asserted in
test_leakage_guard.py, which contains a deliberately-leaky variant of
each family. This file is about the arithmetic being right, and in
particular about what each step returns for the FIRST row of a group --
per the package README, that is where an off-by-one shows up as a value
instead of a crash.

Every expectation below is computed by hand in the test's own comment
rather than by a second implementation, so a test passing means the step
agrees with a human, not with itself.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from feature_fixtures import FIRST_TIP, context, frame_of, team_row, team_schedule

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps.derivation import GameOutcomeStep, RollingMeanStep
from wnba_engine.features.steps.form_steps import (
    BLOWOUT_MARGIN,
    CLOSE_MARGIN,
    ExpandingMeanStep,
    ExponentialMeanStep,
    MarginProfileStep,
    RollingDispersionStep,
    RollingSlopeStep,
    SplitRollingMeanStep,
    StreakStep,
)


def _apply(*steps: object, rows: list[dict[str, object]]) -> object:
    return Pipeline(name="t", steps=steps).run(  # type: ignore[arg-type]
        frame_of(rows), context=context()
    )


def _margins(margins: list[int], *, season: int = 2025) -> list[dict[str, object]]:
    """One team's schedule with an exact point margin per game."""
    return [
        team_row(
            game_id=index + 1,
            team_id=1,
            start_time=FIRST_TIP + timedelta(days=2 * index),
            points_scored=80 + margin,
            points_allowed=80,
            season=season,
        )
        for index, margin in enumerate(margins)
    ]


# -- expanding (season-to-date) mean -----------------------------------


def test_expanding_mean_excludes_the_current_game() -> None:
    """The whole point of ss2's second rule: "this season's average" must
    not contain the game it is being used to predict.
    """
    rows = team_schedule(count=4, scores=[10, 20, 30, 40])
    frame = _apply(ExpandingMeanStep(value_columns=("points_scored",)), rows=rows)
    means = [row["points_scored_season_mean"] for row in frame.rows]  # type: ignore[attr-defined]
    assert means[0] is None  # no prior game
    assert means[1] == pytest.approx(10.0)  # 10
    assert means[2] == pytest.approx(15.0)  # (10+20)/2
    assert means[3] == pytest.approx(20.0)  # (10+20+30)/3


def test_expanding_mean_starts_over_each_season() -> None:
    """Carrying 2025's average into a 2026 opener describes a roster that
    no longer exists.
    """
    rows = [
        *_margins([10, 10], season=2024),
        team_row(game_id=9, team_id=1, start_time=FIRST_TIP + timedelta(days=20),
                 points_scored=90, points_allowed=80, season=2025),
    ]
    frame = _apply(ExpandingMeanStep(value_columns=("points_scored",)), rows=rows)
    assert frame.rows[2]["points_scored_season_mean"] is None  # type: ignore[attr-defined]
    assert frame.rows[2]["season_mean__window_games"] == 0  # type: ignore[attr-defined]


def test_expanding_mean_reports_how_many_games_it_used() -> None:
    rows = team_schedule(count=4)
    frame = _apply(ExpandingMeanStep(value_columns=("points_scored",)), rows=rows)
    counts = [row["season_mean__window_games"] for row in frame.rows]  # type: ignore[attr-defined]
    assert counts == [0, 1, 2, 3]


# -- exponentially weighted mean ---------------------------------------


def test_exponential_mean_weights_recent_games_more() -> None:
    """half_life=1 game means each game back is worth half the last.

    Row 4 sees [10, 20, 30]; weights are 1, 0.5, 0.25 most-recent-first,
    so the value is (30 + 20*0.5 + 10*0.25) / 1.75 = 42.5 / 1.75.
    """
    rows = team_schedule(count=4, scores=[10, 20, 30, 40])
    frame = _apply(
        ExponentialMeanStep(value_columns=("points_scored",), half_life_games=1.0), rows=rows
    )
    values = [row["points_scored_ewm_1"] for row in frame.rows]  # type: ignore[attr-defined]
    assert values[0] is None
    assert values[1] == pytest.approx(10.0)
    assert values[2] == pytest.approx(25.0 / 1.5)
    assert values[3] == pytest.approx(42.5 / 1.75)


def test_exponential_mean_normalises_over_the_history_that_exists() -> None:
    """A team's second game gets its first game's value, not a value
    shrunk toward zero by the history it does not have yet.
    """
    rows = team_schedule(count=2, scores=[42, 0])
    frame = _apply(
        ExponentialMeanStep(value_columns=("points_scored",), half_life_games=10.0), rows=rows
    )
    assert frame.rows[1]["points_scored_ewm_10"] == pytest.approx(42.0)  # type: ignore[attr-defined]


def test_exponential_mean_skips_nulls_like_the_rolling_mean_does() -> None:
    """`pace` is null wherever balldontlie has no advanced-stats row."""
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP, pace=None),
        team_row(game_id=2, team_id=1, start_time=FIRST_TIP + timedelta(days=2), pace=100.0),
        team_row(game_id=3, team_id=1, start_time=FIRST_TIP + timedelta(days=4), pace=None),
    ]
    frame = _apply(ExponentialMeanStep(value_columns=("pace",), half_life_games=5.0), rows=rows)
    assert frame.rows[1]["pace_ewm_5"] is None  # type: ignore[attr-defined]
    assert frame.rows[2]["pace_ewm_5"] == pytest.approx(100.0)  # type: ignore[attr-defined]


def test_exponential_mean_rejects_a_nonsense_half_life() -> None:
    with pytest.raises(StepContractError):
        ExponentialMeanStep(value_columns=("points_scored",), half_life_games=0.0)


def test_exponential_mean_window_count_is_the_weighted_reach_not_all_history() -> None:
    """A raw len(history) would report 225 for a late-2026 game and mean
    nothing next to the other `__window_games` columns, which all answer
    "how many observations went into this number".

    half_life=1 with the default 1e-6 floor reaches log(1e-6)/log(0.5) =
    20 games back, so a 30-game history reports 20, not 30.
    """
    step = ExponentialMeanStep(value_columns=("points_scored",), half_life_games=1.0)
    assert step.effective_lookback == 20

    rows = team_schedule(count=30, gap=timedelta(days=2), scores=list(range(30)))
    frame = _apply(step, rows=rows)
    counts = [row["ewm__window_games"] for row in frame.rows]  # type: ignore[attr-defined]
    assert counts[0] == 0
    assert counts[5] == 5
    assert counts[-1] == 20


def test_exponential_mean_crosses_seasons_unless_told_not_to() -> None:
    """The default is documented and deliberate -- it matches
    RollingMeanStep, which also does not reset -- so it is asserted here
    rather than left to be discovered.
    """
    rows = [
        *_margins([10, 10], season=2024),
        team_row(game_id=9, team_id=1, start_time=FIRST_TIP + timedelta(days=20),
                 points_scored=90, points_allowed=80, season=2025),
    ]
    crossing = _apply(ExponentialMeanStep(value_columns=("points_scored",)), rows=rows)
    resetting = _apply(
        ExponentialMeanStep(value_columns=("points_scored",), season_column="season"), rows=rows
    )
    assert crossing.rows[2]["points_scored_ewm_5"] == pytest.approx(90.0)  # type: ignore[attr-defined]
    assert resetting.rows[2]["points_scored_ewm_5"] is None  # type: ignore[attr-defined]


# -- dispersion (consistency) -------------------------------------------


def test_dispersion_is_the_sample_standard_deviation_of_prior_games() -> None:
    """Row 4 sees [10, 20, 30]: mean 20, sum of squared deviations 200,
    sample variance 200/2 = 100, sd 10.
    """
    rows = team_schedule(count=4, scores=[10, 20, 30, 40])
    frame = _apply(
        RollingDispersionStep(value_columns=("points_scored",), window=3), rows=rows
    )
    values = [row["points_scored_sd_3"] for row in frame.rows]  # type: ignore[attr-defined]
    assert values[0] is None  # nothing prior
    assert values[1] is None  # one observation has no spread
    assert values[2] == pytest.approx(50.0**0.5)  # [10, 20] -> sqrt(50)
    assert values[3] == pytest.approx(10.0)


def test_dispersion_distinguishes_two_teams_with_the_same_mean() -> None:
    """The reason this step exists: 82 every night and 100/64 alternating
    are the same rolling mean and different teams.
    """
    steady = team_schedule(count=4, scores=[82, 82, 82, 82])
    swingy = team_schedule(count=4, scores=[100, 64, 100, 64])
    step = RollingDispersionStep(value_columns=("points_scored",), window=3)
    mean_step = RollingMeanStep(value_columns=("points_scored",), window=3, label="m")

    a = _apply(step, mean_step, rows=steady)
    b = _apply(step, mean_step, rows=swingy)
    assert a.rows[3]["points_scored_mean_3"] == pytest.approx(82.0)  # type: ignore[attr-defined]
    assert b.rows[3]["points_scored_mean_3"] == pytest.approx(88.0)  # type: ignore[attr-defined]
    assert a.rows[3]["points_scored_sd_3"] == pytest.approx(0.0)  # type: ignore[attr-defined]
    assert b.rows[3]["points_scored_sd_3"] > 15.0  # type: ignore[attr-defined,operator]


def test_dispersion_refuses_a_window_of_one() -> None:
    """A one-game window has no spread to measure, so asking for it is a
    configuration error rather than a column of Nones.
    """
    with pytest.raises(StepContractError):
        RollingDispersionStep(value_columns=("points_scored",), window=1)


# -- slope (trend) -------------------------------------------------------


def test_slope_is_positive_for_improving_form_and_negative_for_declining() -> None:
    rising = team_schedule(count=4, scores=[10, 20, 30, 40])
    falling = team_schedule(count=4, scores=[40, 30, 20, 10])
    step = RollingSlopeStep(value_columns=("points_scored",), window=3)

    up = _apply(step, rows=rising)
    down = _apply(step, rows=falling)
    # Row 4 regresses [10, 20, 30] on positions [0, 1, 2] -> slope +10.
    assert up.rows[3]["points_scored_slope_3"] == pytest.approx(10.0)  # type: ignore[attr-defined]
    assert down.rows[3]["points_scored_slope_3"] == pytest.approx(-10.0)  # type: ignore[attr-defined]


def test_slope_is_null_rather_than_zero_with_one_observation() -> None:
    """A line through one point is undefined, not flat -- and 0.0 would
    read as "definitely not trending".
    """
    rows = team_schedule(count=3, scores=[10, 20, 30])
    frame = _apply(RollingSlopeStep(value_columns=("points_scored",), window=3), rows=rows)
    values = [row["points_scored_slope_3"] for row in frame.rows]  # type: ignore[attr-defined]
    assert values[0] is None
    assert values[1] is None
    assert values[2] == pytest.approx(10.0)


def test_slope_separates_two_teams_with_the_same_mean() -> None:
    """The reason this step exists, stated as a test: same average, one
    on the way up and one on the way down.
    """
    rising = team_schedule(count=4, scores=[10, 20, 30, 99])
    falling = team_schedule(count=4, scores=[30, 20, 10, 99])
    step = RollingSlopeStep(value_columns=("points_scored",), window=3)
    mean_step = RollingMeanStep(value_columns=("points_scored",), window=3, label="m")

    up = _apply(step, mean_step, rows=rising)
    down = _apply(step, mean_step, rows=falling)
    assert up.rows[3]["points_scored_mean_3"] == pytest.approx(  # type: ignore[attr-defined]
        down.rows[3]["points_scored_mean_3"]  # type: ignore[attr-defined]
    )
    assert up.rows[3]["points_scored_slope_3"] > 0  # type: ignore[attr-defined,operator]
    assert down.rows[3]["points_scored_slope_3"] < 0  # type: ignore[attr-defined,operator]


# -- home / road splits --------------------------------------------------


def _alternating_venue(scores: list[int]) -> list[dict[str, object]]:
    """Home, away, home, away ... so the splits are trivially checkable."""
    return [
        team_row(
            game_id=index + 1,
            team_id=1,
            start_time=FIRST_TIP + timedelta(days=2 * index),
            points_scored=score,
            is_home=index % 2 == 0,
        )
        for index, score in enumerate(scores)
    ]


def test_home_split_sees_only_prior_home_games() -> None:
    rows = _alternating_venue([10, 20, 30, 40, 50, 60])
    frame = _apply(
        SplitRollingMeanStep(
            value_columns=("points_scored",), window=10,
            split_column="is_home", split_value=True, suffix="home", label="split_home",
        ),
        rows=rows,
    )
    values = [row["points_scored_mean_10_home"] for row in frame.rows]  # type: ignore[attr-defined]
    assert values[0] is None  # first game, no prior home games
    assert values[2] == pytest.approx(10.0)  # prior home games: [10]
    assert values[4] == pytest.approx(20.0)  # prior home games: [10, 30]


def test_road_split_uses_equality_not_truthiness() -> None:
    """split_value=False must mean "away", not "anything falsy" -- a
    truthy test would also swallow a null is_home.
    """
    rows = _alternating_venue([10, 20, 30, 40, 50, 60])
    frame = _apply(
        SplitRollingMeanStep(
            value_columns=("points_scored",), window=10,
            split_column="is_home", split_value=False, suffix="road", label="split_road",
        ),
        rows=rows,
    )
    values = [row["points_scored_mean_10_road"] for row in frame.rows]  # type: ignore[attr-defined]
    assert values[1] is None  # first road game
    assert values[5] == pytest.approx(30.0)  # prior road games: [20, 40]


def test_split_reports_the_thin_sample_the_roadmap_warns_about() -> None:
    """A 10-game home window over 2 home games is a different number and
    has to be legible as one -- the window-count column is what makes the
    distinction available to a caller.
    """
    rows = _alternating_venue([10, 20, 30, 40, 50, 60])
    frame = _apply(
        SplitRollingMeanStep(
            value_columns=("points_scored",), window=10,
            split_column="is_home", split_value=True, suffix="home", label="split_home",
        ),
        rows=rows,
    )
    counts = [row["split_home__window_games"] for row in frame.rows]  # type: ignore[attr-defined]
    assert counts == [0, 1, 1, 2, 2, 3]


def test_split_honours_its_window_length() -> None:
    rows = _alternating_venue([10, 20, 30, 40, 50, 60])
    frame = _apply(
        SplitRollingMeanStep(
            value_columns=("points_scored",), window=1,
            split_column="is_home", split_value=True, suffix="home", label="split_home",
        ),
        rows=rows,
    )
    # Prior home games before game 5 are [10, 30]; window=1 keeps only 30.
    assert frame.rows[4]["points_scored_mean_1_home"] == pytest.approx(30.0)  # type: ignore[attr-defined]


# -- streaks -------------------------------------------------------------


def test_streak_counts_consecutive_results_before_this_game() -> None:
    """Margins +10, +10, -10, -10, +10 -> streaks going IN are
    0 (no prior), +1, +2, -1, -2.
    """
    rows = _margins([10, 10, -10, -10, 10])
    frame = _apply(GameOutcomeStep(), StreakStep(), rows=rows)
    assert [row["win_streak"] for row in frame.rows] == [0, 1, 2, -1, -2]  # type: ignore[attr-defined]


def test_streak_resets_between_seasons_by_default() -> None:
    """A streak carried across a seven-month gap and a roster turnover is
    a claim about a team that no longer exists.
    """
    rows = [
        *_margins([10, 10], season=2024),
        team_row(game_id=9, team_id=1, start_time=FIRST_TIP + timedelta(days=20),
                 points_scored=90, points_allowed=80, season=2025),
    ]
    frame = _apply(GameOutcomeStep(), StreakStep(), rows=rows)
    assert [row["win_streak"] for row in frame.rows] == [0, 1, 0]  # type: ignore[attr-defined]


def test_streak_can_be_asked_to_span_seasons_explicitly() -> None:
    """The cross-season variant is available -- it just has to be asked
    for, rather than being what you get by forgetting.
    """
    rows = [
        *_margins([10, 10], season=2024),
        team_row(game_id=9, team_id=1, start_time=FIRST_TIP + timedelta(days=20),
                 points_scored=90, points_allowed=80, season=2025),
    ]
    frame = _apply(GameOutcomeStep(), StreakStep(season_column=None), rows=rows)
    assert [row["win_streak"] for row in frame.rows] == [0, 1, 2]  # type: ignore[attr-defined]


def test_an_unknown_result_breaks_the_streak_rather_than_extending_it() -> None:
    """`won` is null only when the game has no score. Treating that as a
    continuation asserts something the data does not say.
    """
    rows = _margins([10, 10, 10])
    rows[1] = {**rows[1], "points_scored": None, "points_allowed": None}
    frame = _apply(GameOutcomeStep(), StreakStep(), rows=rows)
    assert [row["win_streak"] for row in frame.rows] == [0, 1, 0]  # type: ignore[attr-defined]


# -- margin profile and blowout rate ------------------------------------


def test_margin_profile_classifies_the_rows_own_game() -> None:
    rows = _margins([BLOWOUT_MARGIN, -BLOWOUT_MARGIN, CLOSE_MARGIN])
    frame = _apply(GameOutcomeStep(), MarginProfileStep(), rows=rows)
    assert frame.rows[0]["is_blowout_win"] is True  # type: ignore[attr-defined]
    assert frame.rows[0]["is_close_game"] is False  # type: ignore[attr-defined]
    assert frame.rows[1]["is_blowout_loss"] is True  # type: ignore[attr-defined]
    assert frame.rows[2]["is_close_game"] is True  # type: ignore[attr-defined]
    assert frame.rows[2]["is_blowout_win"] is False  # type: ignore[attr-defined]


def test_margin_profile_is_null_not_false_for_a_scoreless_game() -> None:
    """A game with no score is not a game that was close, and a rolling
    rate must skip it rather than count it as a non-blowout.
    """
    rows = _margins([10])
    rows[0] = {**rows[0], "points_scored": None, "points_allowed": None}
    frame = _apply(GameOutcomeStep(), MarginProfileStep(), rows=rows)
    assert frame.rows[0]["is_blowout_win"] is None  # type: ignore[attr-defined]
    assert frame.rows[0]["is_close_game"] is None  # type: ignore[attr-defined]


def test_blowout_rate_is_the_rolling_mean_of_the_flag() -> None:
    """The flags are targets; the ROLLED flag is the feature. Two of the
    first four games were blowout wins, so the fifth row sees 0.5.
    """
    rows = _margins([20, 2, 20, 2, 1])
    frame = _apply(
        GameOutcomeStep(),
        MarginProfileStep(),
        RollingMeanStep(
            value_columns=("is_blowout_win",), window=10, label="blowout_rate"
        ),
        rows=rows,
    )
    values = [row["is_blowout_win_mean_10"] for row in frame.rows]  # type: ignore[attr-defined]
    assert values[0] is None
    assert values[1] == pytest.approx(1.0)
    assert values[4] == pytest.approx(0.5)
