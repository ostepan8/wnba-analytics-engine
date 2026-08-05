"""Recoverable prediction-market history: what TRADED, not what was quoted.

`markets.MarketSnapshot` is an observation of mutable state -- the book as it
stood when a cron looked at it. These two are immutable historical facts, and
the difference drives everything about how they are keyed and ingested (see
db/migrations/0025_prediction_market_history.sql).

Both carry `captured_at` anyway. Not as part of their identity, but because
"when did we learn this" stays worth recording even when "when did it happen"
is the anchor -- a backfill run three months late should be legible as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PolymarketTrade:
    """One on-chain fill from data-api.polymarket.com/trades.

    `outcome` is the team name the buyer took, stated by the API. That is the
    single most valuable field here: the snapshot table's probability has no
    recorded side at all for two-way game markets, so a consumer has to infer
    it from title ordering. Nothing here needs inferring.

    `price` is the probability paid, in [0, 1]. `size` is share count, not
    dollars -- notional is price * size, and conflating them overstates
    volume by roughly 2x on a market trading near 0.5.
    """

    transaction_hash: str
    proxy_wallet: str
    asset: str
    side: str
    condition_id: str
    outcome: str | None
    outcome_index: int | None
    price: float
    size: float
    traded_at: datetime
    title: str | None
    slug: str | None
    event_slug: str | None
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class KalshiCandle:
    """One OHLC bar from Kalshi's candlesticks endpoint.

    Three price series, not one: `price_*` is what traded, `yes_bid_*` and
    `yes_ask_*` are the two sides of the book. A bar can carry a bid/ask with
    no trade at all (volume 0), which is a quote nobody hit -- keeping them
    separate is what lets a consumer tell that apart from a real print.

    Every field is optional except the identity: Kalshi omits whole price
    blocks on bars where nothing happened, and a zero there would be a claim
    the exchange never made.
    """

    series_ticker: str
    market_ticker: str
    title: str | None
    period_minutes: int
    period_end: datetime
    price_open: float | None
    price_high: float | None
    price_low: float | None
    price_close: float | None
    price_mean: float | None
    price_previous: float | None
    yes_bid_open: float | None
    yes_bid_high: float | None
    yes_bid_low: float | None
    yes_bid_close: float | None
    yes_ask_open: float | None
    yes_ask_high: float | None
    yes_ask_low: float | None
    yes_ask_close: float | None
    volume: float | None
    open_interest: float | None
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class KalshiTrade:
    """One trade from Kalshi's HISTORICAL tier.

    `yes_price` is stored regardless of which side the taker took, so a
    market's series is directly comparable trade to trade. Kalshi contracts
    settle at $0 or $1, so it is already a probability -- no de-vig, the
    same property that makes Polymarket fills a clean reference.

    `size` is CONTRACTS, not dollars. These markets are an order of
    magnitude more liquid than the WNBA Polymarket ones (median 112,951
    contracts per 2025 market), which matters for any question about
    whether an observed price was actually gettable.
    """

    trade_id: str
    market_ticker: str
    series_ticker: str | None
    yes_price: float
    no_price: float | None
    size: float | None
    taker_side: str | None
    is_block_trade: bool | None
    traded_at: datetime
    captured_at: datetime
