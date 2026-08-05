"""Unit tests for execution-quality statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.analysis.execution import (
    Fill,
    closing_price,
    clv_against_close,
    order_flow_imbalance,
    summarise_execution,
    volume_weighted_price,
)

TIP = datetime(2026, 8, 3, 23, 0, tzinfo=UTC)


def _fill(minutes_before: int, price: float, size: float, side: str = "BUY") -> Fill:
    return Fill(TIP - timedelta(minutes=minutes_before), price, size, side)


def test_vwap_is_a_ratio_of_sums_not_a_mean_of_prices() -> None:
    """A mean over prices weights a 1-share dust trade equally with a
    1000-share one. Same discipline as the per-36 rates in player_steps;
    MODELING_FINDINGS.md measured the mean-of-ratios version costing 2.6x
    MAE in another context.
    """
    fills = [_fill(60, 0.90, 1), _fill(30, 0.50, 999)]
    assert volume_weighted_price(fills) == pytest.approx((0.90 + 0.50 * 999) / 1000)
    # The naive mean would be 0.70 -- nearly 20 points off.
    assert volume_weighted_price(fills) < 0.51


def test_zero_size_fills_do_not_contribute() -> None:
    assert volume_weighted_price([_fill(10, 0.5, 0)]) is None


def test_effective_spread_is_zero_when_everything_prints_at_one_price() -> None:
    fills = [_fill(60, 0.55, 100), _fill(30, 0.55, 200)]
    summary = summarise_execution(fills)
    assert summary.vwap == pytest.approx(0.55)
    assert summary.effective_spread == pytest.approx(0.0)
    assert summary.price_range == pytest.approx(0.0)


def test_effective_spread_grows_with_dispersion_around_vwap() -> None:
    tight = summarise_execution([_fill(60, 0.54, 100), _fill(30, 0.56, 100)])
    wide = summarise_execution([_fill(60, 0.40, 100), _fill(30, 0.70, 100)])
    assert wide.effective_spread > tight.effective_spread


def test_order_flow_imbalance_is_signed_and_bounded() -> None:
    assert order_flow_imbalance([_fill(10, 0.5, 100, "BUY")]) == 1.0
    assert order_flow_imbalance([_fill(10, 0.5, 100, "SELL")]) == -1.0
    balanced = [_fill(10, 0.5, 100, "BUY"), _fill(5, 0.5, 100, "SELL")]
    assert order_flow_imbalance(balanced) == 0.0


def test_order_flow_imbalance_is_none_without_volume() -> None:
    """'No trades' and 'perfectly balanced trades' are different findings
    and a zero would collapse them.
    """
    assert order_flow_imbalance([]) is None


def test_closing_price_is_strictly_before_the_boundary() -> None:
    """A fill at the boundary instant must not be consumed by the thing it
    is meant to predict -- the same strictness the windowed feature steps
    enforce for simultaneous observations.
    """
    fills = [_fill(60, 0.50, 10), _fill(0, 0.99, 10)]
    assert closing_price(fills, before=TIP) == 0.50


def test_closing_price_is_none_when_nothing_traded_in_time() -> None:
    assert closing_price([_fill(-30, 0.6, 10)], before=TIP) is None


def test_clv_sign_follows_the_taker_side() -> None:
    """A silent sign flip here would invert the entire finding, which is
    why an unknown side returns None rather than a guess.
    """
    assert clv_against_close(0.50, 0.56, side="BUY") == pytest.approx(0.06)
    assert clv_against_close(0.50, 0.56, side="SELL") == pytest.approx(-0.06)
    assert clv_against_close(0.50, 0.56, side="MINT") is None


def test_buy_share_is_volume_weighted_not_count_weighted() -> None:
    """One large sell must outweigh several small buys."""
    fills = [
        _fill(60, 0.5, 1, "BUY"),
        _fill(50, 0.5, 1, "BUY"),
        _fill(40, 0.5, 998, "SELL"),
    ]
    summary = summarise_execution(fills)
    assert summary.buy_share == pytest.approx(2 / 1000)
