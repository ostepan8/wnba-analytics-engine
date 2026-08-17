"""Hit rates against a line.

These are the numbers a reader weighs a price with, so the ways they can lie
matter more than the arithmetic: a window that includes the game being
previewed, a push counted as a hit, or a percentage printed from three games.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wnba_engine.analysis.prop_trends import (
    MIN_GAMES_FOR_RATE,
    attach_trends,
    group_history,
    opponents_in_game,
    summarise,
    trends_for_line,
)

BASE = datetime(2026, 8, 1, tzinfo=UTC)


def game(points: int, *, days_ago: int, opponent: int = 1, home: bool = True):
    return {
        "player_id": 7,
        "game_id": 1000 + days_ago,
        "start_time": BASE - timedelta(days=days_ago),
        "points": points,
        "opponent_team_id": opponent,
        "is_home": home,
    }


def window(result: dict, label: str) -> dict:
    return next(w for w in result["windows"] if w["label"] == label)


class TestCounting:
    def test_overs_unders_and_pushes_are_counted_separately(self) -> None:
        result = summarise([20.0, 10.0, 15.0], 15.0, "L3")
        assert (result.overs, result.unders, result.pushes) == (1, 1, 1)

    def test_a_push_is_not_a_hit(self) -> None:
        """Whole-number lines make exact ties common; counting them as overs
        inflates every rate on the page."""
        result = summarise([15.0, 15.0, 15.0, 15.0, 15.0], 15.0, "L5")
        assert result.overs == 0
        assert result.pushes == 5
        assert result.rate is None  # nothing was decided

    def test_pushes_are_excluded_from_the_denominator(self) -> None:
        result = summarise([20.0, 20.0, 20.0, 20.0, 15.0], 15.0, "L5")
        assert result.decided == 4
        assert result.rate == 1.0


class TestSmallSamples:
    def test_a_tiny_window_reports_counts_but_no_rate(self) -> None:
        """"66.7%" from 2-of-3 is exactly the over-reading this project argues
        against everywhere else."""
        result = summarise([20.0, 20.0, 10.0], 15.0, "L3")
        assert result.overs == 2
        assert result.rate is None

    def test_the_threshold_is_where_it_says_it_is(self) -> None:
        just_enough = summarise([20.0] * MIN_GAMES_FOR_RATE, 15.0, "L5")
        one_short = summarise([20.0] * (MIN_GAMES_FOR_RATE - 1), 15.0, "L5")
        assert just_enough.rate == 1.0
        assert one_short.rate is None


class TestWindows:
    def test_l5_uses_only_the_five_most_recent_games(self) -> None:
        history = [game(30, days_ago=index) for index in range(1, 4)] + [
            game(2, days_ago=index) for index in range(4, 21)
        ]
        result = trends_for_line(history, stat_key="points", line=15.0)
        assert window(result, "L5")["games"] == 5
        assert window(result, "L5")["overs"] == 3
        assert window(result, "Season")["games"] == 20

    def test_history_must_already_exclude_the_previewed_game(self) -> None:
        """The function trusts its input to be point-in-time, so the guarantee
        lives in the query (`g.start_time < :before`). This pins the contract:
        what is passed in is what is counted, nothing is filtered here."""
        history = [game(30, days_ago=1), game(30, days_ago=2)]
        result = trends_for_line(history, stat_key="points", line=15.0)
        assert window(result, "L5")["games"] == 2

    def test_opponent_window_only_counts_that_opponent(self) -> None:
        history = [game(30, days_ago=i, opponent=9) for i in range(1, 6)] + [
            game(1, days_ago=i, opponent=3) for i in range(6, 12)
        ]
        result = trends_for_line(history, stat_key="points", line=15.0, opponent_team_id=9)
        versus = window(result, "vs opp")
        assert versus["games"] == 5
        assert versus["overs"] == 5

    def test_no_opponent_window_when_none_is_asked_for(self) -> None:
        result = trends_for_line([game(30, days_ago=1)], stat_key="points", line=15.0)
        assert all(w["label"] != "vs opp" for w in result["windows"])

    def test_home_and_away_split(self) -> None:
        history = [game(30, days_ago=i, home=True) for i in range(1, 6)] + [
            game(4, days_ago=i, home=False) for i in range(6, 11)
        ]
        result = trends_for_line(history, stat_key="points", line=15.0)
        assert window(result, "Home")["overs"] == 5
        assert window(result, "Away")["overs"] == 0

    def test_missing_values_are_skipped_rather_than_counted_as_zero(self) -> None:
        """A null stat is an unrecorded game, not a zero-point game, and
        treating it as zero would drag every average and rate down."""
        history = [game(30, days_ago=1), {**game(0, days_ago=2), "points": None}]
        result = trends_for_line(history, stat_key="points", line=15.0)
        assert window(result, "Season")["games"] == 1
        assert window(result, "Season")["average"] == 30.0


class TestRecentRun:
    def test_each_recent_game_is_labelled_over_under_or_push(self) -> None:
        history = [game(30, days_ago=1), game(15, days_ago=2), game(2, days_ago=3)]
        result = trends_for_line(history, stat_key="points", line=15.0)
        assert [row["cleared"] for row in result["recent"]] == ["over", "push", "under"]


class TestGrouping:
    def test_players_are_split_and_each_sorted_newest_first(self) -> None:
        rows = [
            {"player_id": 1, "start_time": BASE - timedelta(days=5), "points": 1},
            {"player_id": 2, "start_time": BASE - timedelta(days=1), "points": 2},
            {"player_id": 1, "start_time": BASE - timedelta(days=1), "points": 3},
        ]
        grouped = group_history(rows)
        assert set(grouped) == {1, 2}
        assert [row["points"] for row in grouped[1]] == [3, 1]


class TestSideResolution:
    """Which team a player is on decides her opponent window, and getting it
    wrong produces a confidently-labelled 'vs opp' about the wrong defence."""

    def test_a_player_faces_the_other_side_of_the_game(self) -> None:
        history = {
            1: [{"team_id": 10}],
            2: [{"team_id": 13}],
        }
        assert opponents_in_game(history, home_team_id=13, away_team_id=10) == {
            1: 13,
            2: 10,
        }

    def test_a_player_on_neither_side_gets_no_opponent(self) -> None:
        history = {5: [{"team_id": 99}]}
        assert opponents_in_game(history, home_team_id=13, away_team_id=10) == {5: None}

    def test_no_games_yet_gets_no_opponent(self) -> None:
        assert opponents_in_game({5: []}, home_team_id=13, away_team_id=10) == {5: None}


class TestAttachingTrends:
    def test_each_prop_keeps_its_own_fields_and_gains_windows(self) -> None:
        props = [{"player_id": 7, "prop_type": "points", "line": 15.0, "provider": "kalshi"}]
        history = {7: [game(20, days_ago=1), game(10, days_ago=2)]}
        attached = attach_trends(props, history=history, opponent_of={7: 1})
        assert attached[0]["provider"] == "kalshi"
        assert window(attached[0], "Season")["overs"] == 1

    def test_a_market_with_no_box_score_column_is_dropped_not_guessed(self) -> None:
        """Grading a prop against the wrong column yields a confident number
        that is simply about something else."""
        props = [{"player_id": 7, "prop_type": "double_double", "line": 0.5}]
        assert attach_trends(props, history={}, opponent_of={}) == []

    def test_a_player_with_no_history_still_returns_a_row(self) -> None:
        props = [{"player_id": 999, "prop_type": "rebounds", "line": 6.5}]
        attached = attach_trends(props, history={}, opponent_of={})
        assert window(attached[0], "Season")["games"] == 0
