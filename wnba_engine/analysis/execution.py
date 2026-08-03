"""Execution quality: what a fill actually cost, not what was quoted.

Only expressible from `polymarket_trades`. Every other price source in this
project stores QUOTES -- what a venue was advertising when someone looked --
and a quote tells you nothing about whether anyone could get that price in
size, or which side of the spread the taker crossed.

The distinction is not academic. On 2026-08-03 Polymarket quoted 0.43/0.44
on Las Vegas, which is simultaneously "buy Atlanta at 0.57" and "sell
Atlanta at 0.56" -- a 1-cent spread that is 1.8% of a 56-cent contract. Any
CLV or ROI computed off the midpoint silently assumes half of that spread
was free.

`MODELING_FINDINGS.md` records the sharpest reason to care: a strategy with
72.6% price-direction accuracy still returned -1.6% to -7.3% ROI. Direction
was right and execution ate it. These functions measure the part that ate it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Fill:
    """One trade, reduced to what execution analysis needs."""

    at: datetime
    price: float
    size: float
    side: str


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    """How a set of fills executed against their own volume-weighted price.

    `effective_spread` is the mean absolute distance from VWAP, doubled --
    the conventional round-trip measure. Using VWAP as the reference rather
    than a quoted midpoint is deliberate: the midpoint is only recorded
    every 30 minutes by the capture host, while fills are continuous, so a
    midpoint reference would measure our sampling as much as the market.
    """

    fills: int
    volume: float
    vwap: float | None
    effective_spread: float | None
    buy_share: float | None
    price_range: float | None


def volume_weighted_price(fills: Sequence[Fill]) -> float | None:
    """Ratio of sums, never a mean of prices.

    The same discipline `features/steps/player_steps.py` documents for
    per-36 rates: a mean over prices weights a 1-share fill equally with a
    1000-share one. MODELING_FINDINGS.md measured that mistake costing 2.6x
    MAE in another context; here it would make a handful of dust trades
    dominate a market's reported price.
    """
    notional = 0.0
    shares = 0.0
    for fill in fills:
        if fill.size <= 0:
            continue
        notional += fill.price * fill.size
        shares += fill.size
    return notional / shares if shares else None


def summarise_execution(fills: Sequence[Fill]) -> ExecutionSummary:
    """Execution statistics for one market's fills."""
    usable = [f for f in fills if f.size > 0]
    vwap = volume_weighted_price(usable)
    volume = sum(f.size for f in usable)
    if not usable or vwap is None:
        return ExecutionSummary(len(usable), volume, vwap, None, None, None)
    deviations = [abs(f.price - vwap) * f.size for f in usable]
    effective = 2.0 * sum(deviations) / volume if volume else None
    buys = sum(f.size for f in usable if f.side == "BUY")
    prices = [f.price for f in usable]
    return ExecutionSummary(
        fills=len(usable),
        volume=volume,
        vwap=vwap,
        effective_spread=effective,
        buy_share=(buys / volume) if volume else None,
        price_range=max(prices) - min(prices),
    )


def order_flow_imbalance(fills: Sequence[Fill]) -> float | None:
    """(buy volume - sell volume) / total volume, in [-1, 1].

    Impossible from quote snapshots, which is the point -- a snapshot shows
    where the price is, never which side pushed it there.

    READ THE SIGN WITH CARE. Polymarket records BOTH sides of a trade
    on-chain, so a naive sum over all rows nets to roughly zero by
    construction. This is only meaningful over fills already restricted to
    one outcome token (one `asset`), where BUY and SELL genuinely mean
    taking and shedding that specific side.
    """
    buys = sum(f.size for f in fills if f.side == "BUY" and f.size > 0)
    sells = sum(f.size for f in fills if f.side == "SELL" and f.size > 0)
    total = buys + sells
    if total <= 0:
        return None
    return (buys - sells) / total


def closing_price(fills: Sequence[Fill], *, before: datetime) -> float | None:
    """The last traded price strictly before `before`.

    The prediction-market analogue of a closing line, and a better one:
    it is a price someone actually paid, whereas a closing quote is a price
    a book was willing to show. Strictly before, so a fill at the boundary
    instant cannot be consumed by the thing it is meant to predict.
    """
    latest: Fill | None = None
    for fill in sorted(fills, key=lambda f: f.at):
        if fill.at >= before:
            break
        latest = fill
    return latest.price if latest else None


def clv_against_close(entry_price: float, close_price: float, *, side: str) -> float | None:
    """Closing-line value in probability points, from the taker's side.

    Positive means the market moved toward the position after it was
    taken. No de-vig anywhere: Polymarket's two outcomes are complementary
    shares of one dollar, so both prices are already probabilities. That
    makes this the cleanest CLV measurement available in this project --
    every sportsbook version has to strip a margin first, and the
    multiplicative method used there is an approximation.

    Returns None for an unrecognised side rather than guessing, because a
    silent sign flip would invert the entire finding.
    """
    if side == "BUY":
        return close_price - entry_price
    if side == "SELL":
        return entry_price - close_price
    return None
