"""The paper-trade ledger.

The rule this file exists to protect: a metric counts only the rows that
have been graded for it. Treating an ungraded row as 0.0 drags every mean
toward zero, which would make the strategy look worse the more actively it
ran -- a failure that gets more convincing as it gets more wrong.
"""

from __future__ import annotations

import pytest

from wnba_engine.analysis.divergence_report import (
    CLV_REVIEW_THRESHOLD,
    GradedBet,
    split_by_regime,
    summarise,
)


def _bet(**kw) -> GradedBet:
    base = {"edge": 0.01, "in_play": False}
    return GradedBet(**{**base, **kw})


def test_empty_is_not_an_error() -> None:
    s = summarise([])
    assert s.n == 0
    assert s.mean_clv is None
    assert s.survival_rate is None


def test_ungraded_rows_do_not_dilute_clv() -> None:
    """The regression that matters. Two graded at +0.02 and eight
    ungraded must report +0.02, not +0.004.
    """
    bets = [_bet(clv=0.02), _bet(clv=0.02)] + [_bet() for _ in range(8)]
    s = summarise(bets)
    assert s.n == 10
    assert s.n_clv == 2
    assert s.mean_clv == pytest.approx(0.02)


def test_survival_rate_counts_only_rechecked_rows() -> None:
    bets = [_bet(survived=True), _bet(survived=False), _bet()]
    s = summarise(bets)
    assert s.n_survival_graded == 2
    assert s.survival_rate == pytest.approx(0.5)


def test_roi_is_reported_with_its_own_t_stat() -> None:
    """ROI must never appear as a bare number. At realistic n it is noise,
    and the t-stat is what says so.
    """
    bets = [_bet(profit=p) for p in (1.0, -1.0, 1.0, -1.0, 0.9)]
    s = summarise(bets)
    assert s.n_settled == 5
    assert s.roi is not None
    assert s.roi_t is not None


def test_review_threshold_tracks_the_power_calculation() -> None:
    just_under = summarise([_bet(clv=0.01) for _ in range(CLV_REVIEW_THRESHOLD - 1)])
    at_threshold = summarise([_bet(clv=0.01) for _ in range(CLV_REVIEW_THRESHOLD)])
    assert just_under.ready_for_review is False
    assert at_threshold.ready_for_review is True


def test_regimes_are_split_never_pooled() -> None:
    bets = [
        _bet(in_play=False, edge=0.005, clv=0.01),
        _bet(in_play=True, edge=0.030, clv=0.05),
        _bet(in_play=True, edge=0.030, clv=0.05),
    ]
    pre, live = split_by_regime(bets)
    assert pre.n == 1
    assert live.n == 2
    assert pre.mean_edge == pytest.approx(0.005)
    assert live.mean_edge == pytest.approx(0.030)


def test_a_single_observation_gets_no_t_stat() -> None:
    """One point has no standard error. Reporting a t-stat for it would be
    the most confident number in the file and entirely meaningless.
    """
    assert summarise([_bet(clv=0.05)]).clv_t is None


def test_zero_variance_gets_no_t_stat() -> None:
    assert summarise([_bet(clv=0.02) for _ in range(5)]).clv_t is None
