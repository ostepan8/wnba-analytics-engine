"""The named strategies, driven end to end on an in-memory source.

Runs the real pipelines -- loader, cleaning, filters, derivation,
encoding, and the guard after every step -- without Postgres, which is
what makes it cheap to assert the ORDERING properties that a database
test would leave implicit.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from feature_fixtures import FIRST_TIP, context, team_row

from wnba_engine.features import strategies
from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import FeatureError
from wnba_engine.features.source import StaticRowSource


def _team_rows() -> list[dict[str, object]]:
    return [
        team_row(game_id=index + 1, team_id=1, start_time=FIRST_TIP + timedelta(days=2 * index))
        for index in range(6)
    ]


def _player_rows() -> list[dict[str, object]]:
    return [
        {
            "game_id": index + 1,
            "season": 2025,
            "season_type": "regular-season",
            "start_time": FIRST_TIP + timedelta(days=2 * index),
            "player_id": 7,
            "player_name": "A Player",
            "team_id": 1,
            "team_abbrev": "T1",
            "opponent_team_id": 2,
            "is_home": index % 2 == 0,
            "minutes": 30,
            "points": 10 + index,
            "rebounds": 5,
            "assists": 3,
            "three_pointers_made": 1,
            "starter": True,
            "did_not_play": False,
        }
        for index in range(6)
    ]


def test_every_registered_strategy_is_buildable() -> None:
    source = StaticRowSource()
    for name in strategies.STRATEGIES:
        assert strategies.build(name, source).name


def test_unknown_strategy_names_list_the_alternatives() -> None:
    with pytest.raises(FeatureError) as excinfo:
        strategies.build("nope", StaticRowSource())
    assert "team_form" in str(excinfo.value)


def test_situational_baseline_produces_the_phase_one_features() -> None:
    source = StaticRowSource(team_game_rows=_team_rows())
    frame = strategies.situational_baseline(source).run(context=context())

    assert len(frame) == 6
    for column in ("home_away", "rest_days", "is_back_to_back", "point_margin"):
        assert column in frame.column_set
    assert frame.rows[0]["rest_days"] is None


def test_team_form_adds_rolling_and_encoded_columns() -> None:
    source = StaticRowSource(team_game_rows=_team_rows())
    frame = strategies.team_form(source).run(context=context())

    for column in (
        "points_scored_mean_5",
        "pace_mean_5",
        "season_win_pct_prior",
        "home_away_is_home",
        "rest_days_scaled",
        "standings_captured_at",
    ):
        assert column in frame.column_set
    # No standings history in this source, so the join is legitimately empty.
    assert all(row["standings_wins"] is None for row in frame.rows)


def test_team_form_is_the_baseline_plus_steps() -> None:
    """The layering claim, asserted rather than assumed."""
    source = StaticRowSource()
    baseline = strategies.situational_baseline(source)
    rich = strategies.team_form(source)
    assert rich.step_names[: len(baseline.steps)] == baseline.step_names


def test_a_strategy_can_be_thinned_at_the_call_site() -> None:
    source = StaticRowSource(team_game_rows=_team_rows())
    full = strategies.team_form(source)
    lean = full.without("rolling_form_5").without("join_standings_snapshot")

    frame = lean.run(context=context())
    assert "points_scored_mean_5" not in frame.column_set
    assert "pace_mean_5" in frame.column_set
    # ... and the shared factory output is untouched.
    assert "rolling_form_5" in full.step_names


def test_swapping_the_rolling_window_changes_only_that_step() -> None:
    from wnba_engine.features.steps.derivation import RollingMeanStep

    source = StaticRowSource(team_game_rows=_team_rows())
    swapped = strategies.team_form(source).replace_step(
        "rolling_form_5",
        RollingMeanStep(
            value_columns=("points_scored",), window=3, label="rolling_form_5"
        ),
    )
    frame = swapped.run(context=context())
    assert "points_scored_mean_3" in frame.column_set
    assert "points_scored_mean_5" not in frame.column_set


def test_filters_run_before_the_windows_they_would_pollute() -> None:
    """An exhibition against a national team must not sit inside a
    "last 5 games" average -- so it has to be filtered out BEFORE the
    windowed steps, not after.
    """
    names = strategies.team_form(StaticRowSource()).step_names
    assert names.index("franchise_only") < names.index("rest_days")
    assert names.index("season_type") < names.index("rolling_form_5")


def test_player_form_filters_minutes_after_the_windows() -> None:
    """A garbage-time cameo is noise as a ROW and still a real game for
    the player's own history, so the minutes filter runs last.
    """
    names = strategies.player_form(StaticRowSource()).step_names
    assert names[-1] == "minimum_minutes"
    assert names.index("rolling_player_5") < names.index("minimum_minutes")


def test_player_form_rolls_per_player() -> None:
    source = StaticRowSource(player_game_rows=_player_rows())
    frame = strategies.player_form(source).run(context=context())
    assert frame.rows[0]["points_mean_5"] is None
    assert frame.rows[1]["points_mean_5"] == pytest.approx(10.0)
    assert "player_height" in frame.column_set


def test_a_strategy_refuses_rows_from_beyond_the_boundary() -> None:
    """StaticRowSource deliberately does not filter, so this is the guard
    catching a loader that forgot to.
    """
    from wnba_engine.features.errors import LeakageError

    rows = _team_rows()
    rows.append(team_row(game_id=99, team_id=1, start_time=FIRST_TIP + timedelta(days=365)))
    source = StaticRowSource(team_game_rows=rows)
    with pytest.raises(LeakageError):
        strategies.situational_baseline(source).run(context=context())


def test_context_rejects_a_naive_boundary() -> None:
    from datetime import datetime

    with pytest.raises(ValueError):
        FeatureContext(as_of=datetime(2025, 8, 1))  # noqa: DTZ001 -- the point of the test
