"""Pure parsers: raw Polymarket Gamma JSON -> validated domain models.

Verified live against gamma-api.polymarket.com (2026-07):
- GET /events?tag_slug=wnba&closed=false returns a JSON *list* of events,
  each with markets[] carrying pricing directly on the payload: bestBid,
  bestAsk, lastTradePrice (floats in [0, 1]), plus outcomes/outcomePrices as
  JSON-*encoded strings* (e.g. '["0.125", "0.875"]'). No CLOB follow-up call
  is needed for snapshot pricing.
- A bare ?tag=wnba does NOT filter; tag_slug is the working parameter.

Implied probability = outcomePrices[0] (the Yes price) when present,
falling back to the bid/ask midpoint, then lastTradePrice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.markets import MarketSnapshot
from wnba_engine.parsing import optional_datetime_utc, optional_float, require_str

PROVIDER = "polymarket"

STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"
STATUS_INACTIVE = "inactive"


def parse_events(payload: object, *, captured_at: datetime) -> tuple[MarketSnapshot, ...]:
    """Parse a Gamma /events response (a JSON list) into market snapshots."""
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, f"events payload must be a list, got {type(payload).__name__}"
        )
    snapshots: list[MarketSnapshot] = []
    for i, event in enumerate(payload):
        context = f"events[{i}]"
        if not isinstance(event, Mapping):
            raise ProviderValidationError(
                PROVIDER, "event must be an object", context=context
            )
        event_id = require_str(event, "id", PROVIDER, context)
        markets = event.get("markets")
        if markets is None:
            continue
        if not isinstance(markets, Sequence) or isinstance(markets, (str, bytes)):
            raise ProviderValidationError(
                PROVIDER, "markets must be a list", context=context
            )
        for j, market in enumerate(markets):
            snapshots.append(
                _parse_market(market, event_id, f"{context}.markets[{j}]", captured_at)
            )
    return tuple(snapshots)


def _parse_market(
    entry: object, event_id: str, context: str, captured_at: datetime
) -> MarketSnapshot:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "market entry must be an object", context=context)
    market_id = require_str(entry, "id", PROVIDER, context)
    question = require_str(entry, "question", PROVIDER, context)

    yes_bid = _probability(entry.get("bestBid"), f"{context}.bestBid")
    yes_ask = _probability(entry.get("bestAsk"), f"{context}.bestAsk")
    last_price = _probability(entry.get("lastTradePrice"), f"{context}.lastTradePrice")
    yes_price = _parse_yes_outcome_price(entry.get("outcomePrices"), context)

    if yes_price is not None:
        implied = yes_price
    elif yes_bid is not None and yes_ask is not None:
        implied = (yes_bid + yes_ask) / 2
    else:
        implied = last_price

    outcome = entry.get("groupItemTitle")
    return MarketSnapshot(
        provider=PROVIDER,
        market_external_id=market_id,
        event_external_id=event_id,
        title=question,
        outcome=outcome if isinstance(outcome, str) and outcome else None,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        last_price=last_price,
        implied_probability=implied,
        volume=optional_float(entry.get("volumeNum"), PROVIDER, f"{context}.volumeNum"),
        liquidity=optional_float(entry.get("liquidityNum"), PROVIDER, f"{context}.liquidityNum"),
        open_interest=None,
        status=_status(entry),
        close_time=optional_datetime_utc(
            entry.get("endDateIso"), PROVIDER, f"{context}.endDateIso"
        ),
        captured_at=captured_at,
    )


def _parse_yes_outcome_price(value: object, context: str) -> float | None:
    """outcomePrices is a JSON-encoded string like '["0.125", "0.875"]'."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderValidationError(
            PROVIDER, "outcomePrices must be a JSON string", context=f"{context}.outcomePrices"
        )
    try:
        prices = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderValidationError(
            PROVIDER,
            f"outcomePrices is not valid JSON: {value!r}",
            context=f"{context}.outcomePrices",
        ) from exc
    if not isinstance(prices, list) or not prices:
        return None
    return _probability(prices[0], f"{context}.outcomePrices[0]")


def _probability(value: object, context: str) -> float | None:
    parsed = optional_float(value, PROVIDER, context)
    if parsed is None:
        return None
    if not 0.0 <= parsed <= 1.0:
        raise ProviderValidationError(
            PROVIDER, f"probability out of range [0, 1]: {parsed}", context=context
        )
    return parsed


def _status(entry: Mapping[str, object]) -> str:
    if entry.get("closed"):
        return STATUS_CLOSED
    if entry.get("active"):
        return STATUS_ACTIVE
    return STATUS_INACTIVE
