"""Unit tests for FEATURE_ROADMAP.md ss9 play-derived steps."""

from __future__ import annotations

import pytest

from tests.unit.features.feature_fixtures import AS_OF
from wnba_engine.features.context import FeatureContext
from wnba_engine.features.steps import play_steps
from wnba_engine.features.steps.derivation import TARGET_COLUMNS


def _context() -> FeatureContext:
    return FeatureContext(as_of=AS_OF, seasons=(2025,))


def _row(**overrides):
    base = {
        "period_1_points": 20, "period_2_points": 25,
        "period_3_points": 22, "period_4_points": 23,
        "overtime_points": None, "clutch_points": 9,
        "largest_run": 10, "lead_changes": 4, "largest_lead": 14,
    }
    return {**base, **overrides}


def test_scoring_shares_sum_to_one() -> None:
    out = play_steps.ScoringProfileStep().transform(_row(), _context())
    total = sum(out[f"period_{i}_share"] for i in (1, 2, 3, 4))
    assert total == pytest.approx(1.0)
    assert out["second_half_share"] == pytest.approx((22 + 23) / 90)


def test_shares_answer_a_different_question_from_raw_quarter_points() -> None:
    """A team scoring 90 outscores one scoring 70 in every quarter, so raw
    quarter points mostly restate total scoring. Two teams with identical
    SHAPE and different volume must produce identical shares.
    """
    small = play_steps.ScoringProfileStep().transform(
        _row(period_1_points=10, period_2_points=10,
             period_3_points=10, period_4_points=10, clutch_points=4),
        _context(),
    )
    big = play_steps.ScoringProfileStep().transform(
        _row(period_1_points=30, period_2_points=30,
             period_3_points=30, period_4_points=30, clutch_points=12),
        _context(),
    )
    assert small["period_4_share"] == pytest.approx(big["period_4_share"])
    assert small["clutch_share"] == pytest.approx(big["clutch_share"])


def test_a_game_without_play_by_play_yields_nulls_not_zeros() -> None:
    """77 of 1,377 games have no plays. A zero share would assert the team
    scored nothing in that quarter, which is a claim nobody made.
    """
    out = play_steps.ScoringProfileStep().transform(
        _row(period_1_points=None), _context()
    )
    assert all(value is None for value in out.values())


def test_run_dominance_is_the_teams_own_run_against_the_games_largest_lead() -> None:
    out = play_steps.GameVolatilityStep().transform(
        _row(largest_run=12, largest_lead=24), _context()
    )
    assert out["run_dominance"] == pytest.approx(0.5)


def test_lead_change_rate_normalises_for_scoring_volume() -> None:
    """A high-scoring game should not read as chaotic merely for being
    long, so changes are per 100 points of this team's regulation scoring.
    """
    low = play_steps.GameVolatilityStep().transform(
        _row(lead_changes=6, period_1_points=15, period_2_points=15,
             period_3_points=15, period_4_points=15),
        _context(),
    )
    high = play_steps.GameVolatilityStep().transform(
        _row(lead_changes=12, period_1_points=30, period_2_points=30,
             period_3_points=30, period_4_points=30),
        _context(),
    )
    assert low["lead_change_rate"] == pytest.approx(high["lead_change_rate"])


def test_overtime_flag_is_null_rather_than_false_without_plays() -> None:
    """'We do not know' and 'it ended in regulation' are different claims,
    and a rolling overtime RATE has to skip the first, not count it.
    """
    missing = play_steps.GameVolatilityStep().transform(
        _row(overtime_points=None, period_1_points=0, period_2_points=0,
             period_3_points=0, period_4_points=0),
        _context(),
    )
    assert missing["went_to_overtime"] is None
    played = play_steps.GameVolatilityStep().transform(_row(), _context())
    assert played["went_to_overtime"] is False
    ot = play_steps.GameVolatilityStep().transform(
        _row(overtime_points=7), _context()
    )
    assert ot["went_to_overtime"] is True


def test_every_raw_play_column_is_declared_a_target() -> None:
    """The rule this package has now got wrong twice.

    Quarter scoring, runs, lead changes and clutch points all describe the
    game being predicted. The FEATURE is the rolled version; the raw column
    is an outcome, exactly like `points_scored`. `offensive_rating` -- the
    last column class to be missed -- correlated with what the closing line
    got wrong at r = +0.431.
    """
    raw = {
        "period_1_points", "period_2_points", "period_3_points",
        "period_4_points", "overtime_points", "clutch_points",
        "largest_run", "lead_changes", "largest_lead",
    }
    assert raw <= set(TARGET_COLUMNS)
