"""Unit tests for closing line value.

The arithmetic is small; what these pin is the JUDGEMENT -- that a moved
line yields no CLV rather than a wrong one, and that the vig is removed
before any comparison, since otherwise CLV would partly measure the
bookmaker's margin instead of the market's opinion.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.analysis.clv import (
    SIDE_OVER,
    SIDE_UNDER,
    american_to_implied,
    american_to_profit,
    remove_vig,
    score_pick,
    summarize,
)

BET_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
CLOSE_AT = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


def _pick(side: str, bet: tuple[int, int], close: tuple[int, int], *, bet_line=8.5, close_line=8.5):
    return score_pick(
        side=side,
        bet_line=bet_line,
        bet_over_odds=bet[0],
        bet_under_odds=bet[1],
        bet_captured_at=BET_AT,
        close_line=close_line,
        close_over_odds=close[0],
        close_under_odds=close[1],
        close_captured_at=CLOSE_AT,
    )


def test_american_to_implied_known_values():
    assert american_to_implied(-110) == pytest.approx(0.5238, abs=1e-4)
    assert american_to_implied(100) == pytest.approx(0.5)
    assert american_to_implied(-200) == pytest.approx(0.6667, abs=1e-4)
    assert american_to_implied(200) == pytest.approx(0.3333, abs=1e-4)


def test_american_to_profit_known_values():
    assert american_to_profit(-110) == pytest.approx(0.9091, abs=1e-4)
    assert american_to_profit(150) == pytest.approx(1.5)


def test_zero_odds_is_rejected():
    """0 is not a valid American price and would divide by zero downstream."""
    with pytest.raises(ValueError):
        american_to_implied(0)
    with pytest.raises(ValueError):
        american_to_profit(0)


def test_remove_vig_normalizes_to_one():
    prices = remove_vig(-110, -110)
    assert prices.over + prices.under == pytest.approx(1.0)
    assert prices.over == pytest.approx(0.5)
    # A -110/-110 market carries ~4.8% margin.
    assert prices.overround == pytest.approx(1.0476, abs=1e-4)


def test_remove_vig_preserves_the_asymmetry():
    """De-vigging must not flatten a genuinely lopsided market."""
    prices = remove_vig(-300, 250)
    assert prices.over > prices.under
    assert prices.over + prices.under == pytest.approx(1.0)


def test_positive_clv_when_the_market_moves_toward_your_side():
    """Bought the Under at -110, it closed at -140: the market came to
    agree, so the price taken was better than the settled one."""
    result = _pick(SIDE_UNDER, bet=(-110, -110), close=(120, -140))

    assert result.clv is not None
    assert result.clv > 0
    assert result.beat_the_close


def test_negative_clv_when_the_market_moves_away():
    result = _pick(SIDE_UNDER, bet=(120, -140), close=(-140, 120))

    assert result.clv is not None
    assert result.clv < 0
    assert not result.beat_the_close


def test_clv_is_zero_when_nothing_moved():
    result = _pick(SIDE_OVER, bet=(-110, -110), close=(-110, -110))

    assert result.clv == pytest.approx(0.0)
    assert not result.beat_the_close  # strictly positive only


def test_vig_alone_does_not_create_clv():
    """The regression this de-vig exists to prevent: a book widening its
    margin on BOTH sides must not read as the market disagreeing."""
    tight = _pick(SIDE_OVER, bet=(-105, -105), close=(-130, -130))

    assert tight.clv == pytest.approx(0.0, abs=1e-9)


def test_a_moved_line_yields_no_clv_rather_than_a_wrong_one():
    """Under 8.5 and Under 7.5 are different wagers. Differencing their
    probabilities would silently compare apples to oranges, and the
    result would still get averaged."""
    result = _pick(SIDE_UNDER, bet=(-110, -110), close=(-110, -110), close_line=7.5)

    assert result.line_moved
    assert result.clv is None
    assert not result.beat_the_close


def test_summary_excludes_moved_lines_but_keeps_them_visible():
    results = (
        _pick(SIDE_UNDER, bet=(-110, -110), close=(120, -140)),   # +CLV
        _pick(SIDE_UNDER, bet=(120, -140), close=(-140, 120)),    # -CLV
        _pick(SIDE_UNDER, bet=(-110, -110), close=(-110, -110), close_line=7.5),
    )

    summary = summarize(results)

    assert summary.picks == 3
    assert summary.scored == 2
    assert summary.line_moved == 1
    assert summary.beat_close == 1
    assert summary.unscored_share == pytest.approx(1 / 3)


def test_summary_of_only_unscorable_picks_reports_none_not_zero():
    """Zero would read as 'no edge'; None reads as 'not measured'."""
    results = (_pick(SIDE_UNDER, bet=(-110, -110), close=(-110, -110), close_line=7.5),)

    summary = summarize(results)

    assert summary.mean_clv is None
    assert summary.beat_close_rate is None


def test_unknown_side_is_rejected():
    with pytest.raises(ValueError):
        _pick("sideways", bet=(-110, -110), close=(-110, -110))
