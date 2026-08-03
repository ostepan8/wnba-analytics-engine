"""Matchup features: the numbers.

Leakage properties live in test_leakage_guard.py, which carries a
head-to-head step written the wrong way and asserts it is rejected. This
file is about the arithmetic, and about the two properties that are easy
to get backwards on a two-rows-per-game frame:

- head-to-head is keyed on the ORDERED pair, so team A's row carries A's
  record against B and team B's row carries B's against A. Getting that
  wrong produces a frame where every win percentage is 0.5 and nothing
  looks broken.
- rest advantage is signed FROM THIS ROW'S POINT OF VIEW. A sign error
  is invisible in aggregate and inverts the feature.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from feature_fixtures import FIRST_TIP, context, frame_of, team_row

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.steps.derivation import (
    GameOutcomeStep,
    OpponentFormStep,
    RestDaysStep,
)
from wnba_engine.features.steps.matchup_steps import (
    HeadToHeadStep,
    PaceInteractionStep,
    RestAdvantageStep,
)


def _apply(*steps: object, rows: list[dict[str, object]]) -> object:
    return Pipeline(name="t", steps=steps).run(  # type: ignore[arg-type]
        frame_of(rows), context=context()
    )


def _meeting(
    game_id: int,
    *,
    at,
    home_points: int,
    away_points: int,
    season: int = 2025,
) -> list[dict[str, object]]:
    """Both sides of one game between team 1 (home) and team 2 (away).

    A team-game frame is two rows per game, and every matchup feature is
    computed from that structure, so the fixture has to produce it.
    """
    return [
        team_row(game_id=game_id, team_id=1, start_time=at, is_home=True,
                 points_scored=home_points, points_allowed=away_points, season=season)
        | {"opponent_team_id": 2},
        team_row(game_id=game_id, team_id=2, start_time=at, is_home=False,
                 points_scored=away_points, points_allowed=home_points, season=season)
        | {"opponent_team_id": 1},
    ]


# -- rest advantage ------------------------------------------------------


def _rest_pipeline(rows: list[dict[str, object]]) -> object:
    return _apply(
        RestDaysStep(),
        OpponentFormStep(
            value_columns=("rest_days", "is_back_to_back"),
            source_window_end_column="rest_days__window_end",
            label="opponent_rest",
        ),
        RestAdvantageStep(),
        rows=rows,
    )


def test_rest_advantage_is_signed_from_this_rows_point_of_view() -> None:
    """Team 1 plays on days 0 and 6 (six days rest); team 2 plays on days
    4 and 6 (two days rest). Team 1's row must read +4, team 2's -4.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"opponent_team_id": 9},
        team_row(game_id=2, team_id=2, start_time=FIRST_TIP + timedelta(days=4))
        | {"opponent_team_id": 9},
        *_meeting(3, at=FIRST_TIP + timedelta(days=6), home_points=80, away_points=70),
    ]
    frame = _rest_pipeline(rows)
    by_team = {row["team_id"]: row for row in frame.rows if row["game_id"] == 3}  # type: ignore[attr-defined]
    assert by_team[1]["rest_advantage"] == pytest.approx(4.0)
    assert by_team[2]["rest_advantage"] == pytest.approx(-4.0)


def test_rest_advantage_is_null_when_either_side_has_no_prior_game() -> None:
    """Calling a season opener "equal rest" invents the one value most
    likely to look like the average.
    """
    rows = _meeting(1, at=FIRST_TIP, home_points=80, away_points=70)
    frame = _rest_pipeline(rows)
    assert all(row["rest_advantage"] is None for row in frame.rows)  # type: ignore[attr-defined]


def test_back_to_back_edge_fires_only_when_exactly_one_side_is_on_one() -> None:
    """A rested team against a back-to-back is a categorically different
    game, and a linear term in a difference of days cannot express it.
    """
    rows = [
        # Team 2 played yesterday; team 1 played a week ago.
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"opponent_team_id": 9},
        team_row(game_id=2, team_id=2, start_time=FIRST_TIP + timedelta(days=6))
        | {"opponent_team_id": 9},
        *_meeting(3, at=FIRST_TIP + timedelta(days=7), home_points=80, away_points=70),
    ]
    frame = _rest_pipeline(rows)
    by_team = {row["team_id"]: row for row in frame.rows if row["game_id"] == 3}  # type: ignore[attr-defined]
    assert by_team[1]["back_to_back_edge"] == 1  # only the opponent is tired
    assert by_team[2]["back_to_back_edge"] == -1


def test_back_to_back_edge_is_zero_when_both_sides_are_on_one() -> None:
    """"Neither" and "both" are the same RELATIVE advantage even though
    they are very different games -- which is why the absolute flags stay
    in the frame alongside this one.
    """
    rows = [
        team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"opponent_team_id": 9},
        team_row(game_id=2, team_id=2, start_time=FIRST_TIP) | {"opponent_team_id": 9},
        *_meeting(3, at=FIRST_TIP + timedelta(days=1), home_points=80, away_points=70),
    ]
    frame = _rest_pipeline(rows)
    for row in (r for r in frame.rows if r["game_id"] == 3):  # type: ignore[attr-defined]
        assert row["is_back_to_back"] is True
        assert row["back_to_back_edge"] == 0


# -- pace interaction ----------------------------------------------------


def _paced(own: float | None, opponent: float | None) -> dict[str, object]:
    return team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {
        "pace_mean_5": own,
        "opponent_pace_mean_5": opponent,
    }


def test_pace_interaction_summarises_the_pair_without_a_threshold() -> None:
    """Both-fast is a high min, both-slow is a low max, a mismatch is a
    large gap -- so the buckets are recoverable without a cut point that
    would either be fitted on the frame or hard-code a pace era.
    """
    frame = _apply(PaceInteractionStep(), rows=[_paced(100.0, 80.0)])
    row = frame.rows[0]  # type: ignore[attr-defined]
    assert row["pace_pair_mean"] == pytest.approx(90.0)
    assert row["pace_pair_min"] == pytest.approx(80.0)
    assert row["pace_pair_max"] == pytest.approx(100.0)
    assert row["pace_pair_gap"] == pytest.approx(20.0)


def test_pace_interaction_gap_is_unsigned() -> None:
    """A mismatch is a mismatch either way round. The SIGNED version is
    `style_steps.StyleDistanceStep`'s `pace_gap`, which is a different
    feature in a different strategy.
    """
    fast_home = _apply(PaceInteractionStep(), rows=[_paced(100.0, 80.0)])
    slow_home = _apply(PaceInteractionStep(), rows=[_paced(80.0, 100.0)])
    assert fast_home.rows[0]["pace_pair_gap"] == slow_home.rows[0]["pace_pair_gap"]  # type: ignore[attr-defined]


def test_pace_interaction_is_null_when_either_side_has_no_rolling_pace() -> None:
    """`pace` is null wherever balldontlie has no advanced-stats row.
    Halving one team's pace to stand in for the pair is a number nobody
    measured.
    """
    frame = _apply(PaceInteractionStep(), rows=[_paced(100.0, None)])
    row = frame.rows[0]  # type: ignore[attr-defined]
    assert row["pace_pair_mean"] is None
    assert row["pace_pair_min"] is None


# -- head to head --------------------------------------------------------


def _series(results: list[tuple[int, int]], *, season: int = 2025) -> list[dict[str, object]]:
    """`results` are (home points, away points) for team 1 vs team 2."""
    rows: list[dict[str, object]] = []
    for index, (home, away) in enumerate(results):
        rows.extend(
            _meeting(
                index + 1,
                at=FIRST_TIP + timedelta(days=3 * index),
                home_points=home,
                away_points=away,
                season=season,
            )
        )
    return rows


def test_head_to_head_excludes_the_current_meeting() -> None:
    """The hazard FEATURE_ROADMAP.md names for both ss3 head-to-head
    rows. Three meetings; the third row must see two.
    """
    rows = _series([(80, 70), (90, 70), (60, 70)])
    frame = _apply(
        GameOutcomeStep(), HeadToHeadStep(prefix="h2h_season"), rows=rows
    )
    team_one = [row for row in frame.rows if row["team_id"] == 1]  # type: ignore[attr-defined]
    assert [row["h2h_season_games_prior"] for row in team_one] == [0, 1, 2]


def test_head_to_head_is_keyed_on_the_ordered_pair() -> None:
    """Team 1 wins all three; team 1's rows must read a rising win rate
    and team 2's a falling one. Keying on an unordered pair would give
    both sides the same number and look plausible.
    """
    rows = _series([(80, 70), (90, 70), (85, 70)])
    frame = _apply(GameOutcomeStep(), HeadToHeadStep(prefix="h2h_season"), rows=rows)
    by_team = {1: [], 2: []}  # type: ignore[var-annotated]
    for row in frame.rows:  # type: ignore[attr-defined]
        by_team[row["team_id"]].append(row["h2h_season_win_pct_prior"])
    assert by_team[1] == [None, 1.0, 1.0]
    assert by_team[2] == [None, 0.0, 0.0]


def test_head_to_head_margin_is_the_mean_of_prior_meetings() -> None:
    """Margins for team 1 are +10 then +20, so its third meeting sees 15
    and team 2's sees -15.
    """
    rows = _series([(80, 70), (90, 70), (85, 70)])
    frame = _apply(GameOutcomeStep(), HeadToHeadStep(prefix="h2h_season"), rows=rows)
    third = {row["team_id"]: row for row in frame.rows if row["game_id"] == 3}  # type: ignore[attr-defined]
    assert third[1]["h2h_season_margin_mean_prior"] == pytest.approx(15.0)
    assert third[2]["h2h_season_margin_mean_prior"] == pytest.approx(-15.0)


def test_season_scoped_head_to_head_forgets_last_years_meetings() -> None:
    rows = [
        *_series([(80, 70), (90, 70)], season=2024),
        *[
            row
            for row in _meeting(
                9, at=FIRST_TIP + timedelta(days=20), home_points=85, away_points=70,
                season=2025,
            )
        ],
    ]
    seasonal = _apply(GameOutcomeStep(), HeadToHeadStep(prefix="h2h_season"), rows=rows)
    all_time = _apply(
        GameOutcomeStep(), HeadToHeadStep(prefix="h2h_all", season_column=None), rows=rows
    )
    last = {row["game_id"]: row for row in seasonal.rows if row["team_id"] == 1}[9]  # type: ignore[attr-defined]
    last_all = {row["game_id"]: row for row in all_time.rows if row["team_id"] == 1}[9]  # type: ignore[attr-defined]
    assert last["h2h_season_games_prior"] == 0
    assert last_all["h2h_all_games_prior"] == 2


def test_head_to_head_can_be_capped_at_the_last_n_meetings() -> None:
    """A multi-season record reaches back through roster turnover, so
    "the last 2 meetings" is a different and defensible question.
    """
    rows = _series([(80, 70), (90, 70), (60, 70), (65, 70)])
    frame = _apply(
        GameOutcomeStep(),
        HeadToHeadStep(prefix="h2h_recent", season_column=None, window=2),
        rows=rows,
    )
    fourth = {row["team_id"]: row for row in frame.rows if row["game_id"] == 4}  # type: ignore[attr-defined]
    # Last two meetings before game 4 were a win (+20) and a loss (-10).
    assert fourth[1]["h2h_recent_games_prior"] == 2
    assert fourth[1]["h2h_recent_wins_prior"] == 1
    assert fourth[1]["h2h_recent_margin_mean_prior"] == pytest.approx(5.0)


def test_head_to_head_does_not_count_a_scoreless_meeting_as_a_loss() -> None:
    """`won` is null when a game has no score. Counting the null as a
    loss would invent a result, and dividing by the full meeting count
    would understate every win rate.
    """
    rows = _series([(80, 70), (90, 70)])
    rows[0] = {**rows[0], "points_scored": None, "points_allowed": None}
    rows[1] = {**rows[1], "points_scored": None, "points_allowed": None}
    frame = _apply(GameOutcomeStep(), HeadToHeadStep(prefix="h2h_season"), rows=rows)
    second = {row["team_id"]: row for row in frame.rows if row["game_id"] == 2}  # type: ignore[attr-defined]
    assert second[1]["h2h_season_games_prior"] == 1  # the meeting happened
    assert second[1]["h2h_season_wins_prior"] == 0
    assert second[1]["h2h_season_win_pct_prior"] is None  # but its result is unknown


def test_head_to_head_rejects_a_nonsense_configuration() -> None:
    with pytest.raises(StepContractError):
        HeadToHeadStep(prefix="")
    with pytest.raises(StepContractError):
        HeadToHeadStep(prefix="h2h", window=0)
