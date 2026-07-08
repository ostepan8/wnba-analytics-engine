"""Canonical prediction-market snapshot shape (Kalshi, Polymarket, ...).

Prices are normalized to probabilities in [0, 1] regardless of how the
provider quotes them (Kalshi quotes dollar strings like "0.4100";
Polymarket quotes floats). Snapshots are append-only time series rows —
we keep price history, never overwrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    provider: str
    market_external_id: str
    event_external_id: str | None
    title: str
    outcome: str | None
    yes_bid: float | None
    yes_ask: float | None
    last_price: float | None
    implied_probability: float | None
    volume: float | None
    liquidity: float | None
    open_interest: float | None
    status: str
    close_time: datetime | None
    captured_at: datetime
