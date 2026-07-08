"""Pure parsers: raw Kalshi JSON -> validated domain models.

Verified live against api.elections.kalshi.com/trade-api/v2 (2026-07):
- GET /series?category=Sports  -> {"series": [{ticker, title, category, ...}]}
- GET /markets?series_ticker=X -> {"cursor": "...", "markets": [...]}

Price fields: the legacy integer-cent fields (yes_bid, last_price, ...) now
come back null; the API quotes dollar *strings* instead — yes_bid_dollars,
yes_ask_dollars, last_price_dollars ("0.4100" == 41 cents == 0.41 implied
probability), with volumes in *_fp fields ("1883.84"). We normalize all
prices to probabilities in [0, 1].
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.markets import MarketSnapshot
from wnba_engine.parsing import (
    optional_datetime_utc,
    optional_float,
    require_sequence,
    require_str,
)

PROVIDER = "kalshi"
WNBA_KEYWORD = "WNBA"


@dataclass(frozen=True, slots=True)
class KalshiSeries:
    """A Kalshi series (market family), e.g. KXWNBAGAME."""

    ticker: str
    title: str
    category: str | None


def parse_series_list(payload: object) -> tuple[KalshiSeries, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"series payload must be an object, got {type(payload).__name__}"
        )
    raw_series = require_sequence(payload, "series", PROVIDER, "series")
    result = []
    for i, entry in enumerate(raw_series):
        context = f"series[{i}]"
        if not isinstance(entry, Mapping):
            raise ProviderValidationError(
                PROVIDER, "series entry must be an object", context=context
            )
        category = entry.get("category")
        result.append(
            KalshiSeries(
                ticker=require_str(entry, "ticker", PROVIDER, context),
                title=require_str(entry, "title", PROVIDER, context),
                category=category if isinstance(category, str) else None,
            )
        )
    return tuple(result)


def filter_wnba_series(series: tuple[KalshiSeries, ...]) -> tuple[KalshiSeries, ...]:
    """Client-side filter: Kalshi has no WNBA category, so match on keyword."""
    return tuple(
        s for s in series if WNBA_KEYWORD in s.ticker.upper() or WNBA_KEYWORD in s.title.upper()
    )


def parse_markets_page(
    payload: object, *, captured_at: datetime
) -> tuple[tuple[MarketSnapshot, ...], str | None]:
    """Parse one page of /markets into snapshots plus the next-page cursor."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"markets payload must be an object, got {type(payload).__name__}"
        )
    raw_markets = require_sequence(payload, "markets", PROVIDER, "markets")
    snapshots = tuple(
        _parse_market(entry, f"markets[{i}]", captured_at)
        for i, entry in enumerate(raw_markets)
    )
    cursor = payload.get("cursor")
    return snapshots, cursor if isinstance(cursor, str) and cursor else None


def _parse_market(entry: object, context: str, captured_at: datetime) -> MarketSnapshot:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "market entry must be an object", context=context)
    ticker = require_str(entry, "ticker", PROVIDER, context)
    yes_bid = _probability(entry.get("yes_bid_dollars"), f"{context}.yes_bid_dollars")
    yes_ask = _probability(entry.get("yes_ask_dollars"), f"{context}.yes_ask_dollars")
    last_price = _probability(entry.get("last_price_dollars"), f"{context}.last_price_dollars")

    if yes_bid is not None and yes_ask is not None:
        implied = (yes_bid + yes_ask) / 2
    else:
        implied = last_price

    event_ticker = entry.get("event_ticker")
    outcome = entry.get("yes_sub_title")
    title = entry.get("title")
    return MarketSnapshot(
        provider=PROVIDER,
        market_external_id=ticker,
        event_external_id=event_ticker if isinstance(event_ticker, str) else None,
        title=title if isinstance(title, str) and title else ticker,
        outcome=outcome if isinstance(outcome, str) and outcome else None,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        last_price=last_price,
        implied_probability=implied,
        volume=optional_float(entry.get("volume_fp"), PROVIDER, f"{context}.volume_fp"),
        liquidity=optional_float(
            entry.get("liquidity_dollars"), PROVIDER, f"{context}.liquidity_dollars"
        ),
        open_interest=optional_float(
            entry.get("open_interest_fp"), PROVIDER, f"{context}.open_interest_fp"
        ),
        status=require_str(entry, "status", PROVIDER, context),
        close_time=optional_datetime_utc(
            entry.get("close_time"), PROVIDER, f"{context}.close_time"
        ),
        captured_at=captured_at,
    )


def _probability(value: object, context: str) -> float | None:
    parsed = optional_float(value, PROVIDER, context)
    if parsed is None:
        return None
    if not 0.0 <= parsed <= 1.0:
        raise ProviderValidationError(
            PROVIDER, f"probability out of range [0, 1]: {parsed}", context=context
        )
    return parsed
