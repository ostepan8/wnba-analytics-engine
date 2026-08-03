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
    ):
        assert column in frame.column_set
    # Standings are deliberately NOT in the default strategy:
    # team_standings_history only begins 2026-07-09, so the join would be
    # all-null across 2022-2025. See team_form's docstring.
    assert "standings_wins" not in frame.column_set


def test_team_form_multi_is_team_form_plus_the_multi_window_block() -> None:
    """The layering claim for ss2, asserted rather than assumed: every
    team_form step survives, and the new ones sit with the other windowed
    work rather than after the encoders.
    """
    source = StaticRowSource()
    base = strategies.team_form(source).step_names
    rich = strategies.team_form_multi(source).step_names

    assert set(base) < set(rich)
    assert rich.index("season_form") < rich.index("one_hot_home_away")
    # The blowout flags describe the row's own game; the ROLLED flag is
    # the feature, so the pair must stay in that order.
    assert rich.index("margin_profile") < rich.index("margin_profile_10")


def test_team_form_multi_produces_level_shape_and_streak_columns() -> None:
    source = StaticRowSource(team_game_rows=_team_rows())
    frame = strategies.team_form_multi(source).run(context=context())

    for column in (
        "points_scored_mean_10",
        "points_scored_mean_20",
        "point_margin_season_mean",
        "point_margin_ewm_5",
        "point_margin_sd_10",
        "point_margin_slope_10",
        "point_margin_mean_10_home",
        "point_margin_mean_10_road",
        "win_streak",
        "is_blowout_win_mean_10",
        "split_home__window_games",
    ):
        assert column in frame.column_set


def test_team_form_is_unchanged_by_the_multi_window_strategy() -> None:
    """team_form_multi is a separate strategy precisely so the cheap one
    stays cheap; if this ever fails, the two have been merged and the
    docstring's argument needs revisiting.
    """
    source = StaticRowSource(team_game_rows=_team_rows())
    frame = strategies.team_form(source).run(context=context())
    assert "point_margin_sd_10" not in frame.column_set
    assert "win_streak" not in frame.column_set


def _matchup_rows() -> list[dict[str, object]]:
    """Two teams meeting four times -- the structure every ss3 feature
    is computed from.
    """
    rows: list[dict[str, object]] = []
    for index in range(4):
        at = FIRST_TIP + timedelta(days=3 * index)
        rows.append(
            team_row(game_id=index + 1, team_id=1, start_time=at, is_home=True,
                     points_scored=80 + index, points_allowed=70)
            | {"opponent_team_id": 2}
        )
        rows.append(
            team_row(game_id=index + 1, team_id=2, start_time=at, is_home=False,
                     points_scored=70, points_allowed=80 + index)
            | {"opponent_team_id": 1}
        )
    return rows


def test_team_matchup_adds_the_relational_columns() -> None:
    source = StaticRowSource(team_game_rows=_matchup_rows())
    frame = strategies.team_matchup(source).run(context=context())

    for column in (
        "opponent_rest_days",
        "rest_advantage",
        "back_to_back_edge",
        "pace_pair_mean",
        "pace_pair_min",
        "pace_pair_gap",
        "h2h_season_games_prior",
        "h2h_season_win_pct_prior",
        "h2h_all_margin_mean_prior",
    ):
        assert column in frame.column_set


def test_the_rest_mirror_runs_before_the_step_that_reads_it() -> None:
    """A mirror and the step consuming it are a pair; reversing them is a
    frame-contract error rather than a column of nulls, but the ordering
    is what makes that true.
    """
    names = strategies.team_matchup(StaticRowSource()).step_names
    assert names.index("rest_days") < names.index("opponent_rest")
    assert names.index("opponent_rest") < names.index("rest_advantage")
    assert names.index("rolling_pace_5") < names.index("pace_interaction")


def test_team_matchup_head_to_head_reflects_the_actual_series() -> None:
    """Team 1 wins every meeting, so its later rows read a 1.0 prior win
    rate and team 2's read 0.0. If the key were unordered both would read
    0.5 and nothing would look wrong.
    """
    source = StaticRowSource(team_game_rows=_matchup_rows())
    frame = strategies.team_matchup(source).run(context=context())
    last = {row["team_id"]: row for row in frame.rows if row["game_id"] == 4}
    assert last[1]["h2h_season_win_pct_prior"] == pytest.approx(1.0)
    assert last[2]["h2h_season_win_pct_prior"] == pytest.approx(0.0)
    assert last[1]["h2h_season_games_prior"] == 3


def test_the_matchup_block_composes_onto_the_multi_window_strategy() -> None:
    """The documented escape hatch: ss2 and ss3 are separate strategies
    precisely so a caller wanting both says so in one line.
    """
    source = StaticRowSource(team_game_rows=_matchup_rows())
    combined = strategies.team_form_multi(source).with_steps(strategies.matchup_block())
    frame = combined.run(context=context())
    assert "point_margin_sd_10" in frame.column_set
    assert "rest_advantage" in frame.column_set


def test_standings_can_be_layered_back_on() -> None:
    """The removal is a composition choice, not a deletion -- re-adding the
    step is one call, which is the point of the pipeline being composable."""
    from wnba_engine.features.steps.loading import JoinStandingsSnapshotStep

    source = StaticRowSource(team_game_rows=_team_rows())
    with_standings = strategies.team_form(source).with_steps(
        (JoinStandingsSnapshotStep(source=source),)
    )

    frame = with_standings.run(context=context())
    assert "standings_wins" in frame.column_set
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
    lean = full.without("rolling_form_5").without("opponent_rolling_form_5")

    frame = lean.run(context=context())
    assert "points_scored_mean_5" not in frame.column_set
    assert "pace_mean_5" in frame.column_set
    # ... and the shared factory output is untouched.
    assert "rolling_form_5" in full.step_names


def test_swapping_the_rolling_window_changes_only_that_step() -> None:
    from wnba_engine.features.steps.derivation import RollingMeanStep

    source = StaticRowSource(team_game_rows=_team_rows())
    # The mirror reads rolling_form_5's output columns, so swapping the
    # window means swapping both -- see team_form's docstring.
    swapped = (
        strategies.team_form(source)
        .without("opponent_rolling_form_5")
        .replace_step(
            "rolling_form_5",
            RollingMeanStep(
                value_columns=("points_scored",), window=3, label="rolling_form_5"
            ),
        )
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


def _rate_rows() -> list[dict[str, object]]:
    """Two players on one team, so a minutes share has a denominator."""
    rows: list[dict[str, object]] = []
    for index in range(6):
        at = FIRST_TIP + timedelta(days=2 * index)
        for player_id, minutes, points in ((7, 30, 15), (8, 10, 4)):
            rows.append(
                {
                    "game_id": index + 1,
                    "season": 2025,
                    "season_type": "regular-season",
                    "start_time": at,
                    "player_id": player_id,
                    "player_name": f"Player {player_id}",
                    "team_id": 1,
                    "team_abbrev": "T1",
                    "opponent_team_id": 2,
                    "is_home": index % 2 == 0,
                    "minutes": minutes,
                    "points": points,
                    "rebounds": 5,
                    "assists": 3,
                    "three_pointers_made": 1,
                    "starter": player_id == 7,
                    "did_not_play": False,
                    "field_goals_attempted": 12,
                    "three_pointers_attempted": 4,
                    "free_throws_attempted": 3,
                    "offensive_rebounds": 2,
                    "steals": 1,
                    "blocks": 1,
                    "turnovers": 2,
                    "usage_pct": 0.2,
                    "true_shooting_pct": 0.55,
                    "assist_pct": 0.15,
                    "rebound_pct": 0.08,
                    "pie": 0.1,
                }
            )
    return rows


def test_player_rates_adds_rates_role_and_the_style_vector() -> None:
    source = StaticRowSource(player_game_rows=_rate_rows())
    frame = strategies.player_rates(source).run(context=context())

    for column in (
        "points_per36_10",
        "turnovers_per36_10",
        "three_pointers_attempted_share_of_fga_10",
        "offensive_rebounds_share_of_reb_10",
        "usage_pct_wmean_10",
        "pie_wmean_10",
        "minutes_share_10",
        "starter_mean_10",
        "usage_pct_is_null",
    ):
        assert column in frame.column_set


def test_player_rates_minutes_share_matches_the_rotation() -> None:
    """Player 7 takes 30 of the team's 40 minutes every game, so their
    share is 0.75 once there is any history.
    """
    source = StaticRowSource(player_game_rows=_rate_rows())
    frame = strategies.player_rates(source).run(context=context())
    later = [r for r in frame.rows if r["player_id"] == 7 and r["game_id"] == 6]
    assert later[0]["minutes_share_10"] == pytest.approx(0.75)


def test_player_rates_keeps_the_minutes_filter_last() -> None:
    """Same reason as player_form: a cameo is noise as a row and is still
    real history for every rate above it. Filtering earlier would silently
    redefine every rate as "over games with real minutes", which HIDES the
    low-minute bias the ratio of sums exists to handle rather than fixing
    it.
    """
    names = strategies.player_rates(StaticRowSource()).step_names
    assert names[-1] == "minimum_minutes"
    for step in ("per36_10", "advanced_10", "minutes_share_10", "starter_rate_10"):
        assert names.index(step) < names.index("minimum_minutes")


def test_player_rates_coerces_before_it_windows() -> None:
    """The advanced columns are NUMERIC, so psycopg hands back Decimal and
    the first window would raise TypeError on contact with a float.
    """
    names = strategies.player_rates(StaticRowSource()).step_names
    assert names.index("coerce_player_rates") < names.index("advanced_10")


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
