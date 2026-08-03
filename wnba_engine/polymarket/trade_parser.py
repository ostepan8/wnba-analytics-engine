"""Pure parser: data-api.polymarket.com/trades JSON -> PolymarketTrade.

Verified live against the endpoint on 2026-08-03. The response is a bare JSON
*list* of fill objects (no envelope, no cursor), paginated with limit/offset.
Fields observed on every record:

    proxyWallet side asset conditionId size price timestamp title slug
    icon eventSlug outcome outcomeIndex name pseudonym bio profileImage
    profileImageOptimized transactionHash

The profile fields (name/pseudonym/bio/profileImage*) are a trader's public
display identity and are deliberately dropped: they are mutable, they are
personal data this project has no use for, and keeping them would make an
immutable-facts table mutable again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.market_history import PolymarketTrade
from wnba_engine.parsing import optional_int, optional_str, parse_float, require_str

PROVIDER = "polymarket"


def parse_trades(
    payload: object, *, captured_at: datetime, context: str = "trades"
) -> tuple[PolymarketTrade, ...]:
    """Parse a /trades response into fills, oldest-first ordering preserved.

    Order is NOT normalized here. The endpoint returns newest-first and the
    caller paginates with offset; re-sorting inside the parser would hide a
    pagination bug that skipped a page, because the result would still look
    like a clean series.
    """
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, f"trades payload must be a list, got {type(payload).__name__}",
            context=context,
        )
    return tuple(
        _parse_trade(entry, f"{context}[{i}]", captured_at)
        for i, entry in enumerate(payload)
    )


def _parse_trade(entry: object, context: str, captured_at: datetime) -> PolymarketTrade:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "trade must be an object", context=context)

    side = require_str(entry, "side", PROVIDER, context).upper()
    if side not in ("BUY", "SELL"):
        # Not merely unexpected -- side determines which direction a fill
        # moves the implied probability, so a third value silently inverts
        # any flow analysis built on this table.
        raise ProviderValidationError(
            PROVIDER, f"side must be BUY or SELL, got {side!r}", context=context
        )

    price = parse_float(entry.get("price"), PROVIDER, f"{context}.price")
    if not 0.0 <= price <= 1.0:
        raise ProviderValidationError(
            PROVIDER, f"price must be a probability in [0, 1], got {price}", context=context
        )
    size = parse_float(entry.get("size"), PROVIDER, f"{context}.size")
    if size < 0:
        raise ProviderValidationError(
            PROVIDER, f"size must be non-negative, got {size}", context=context
        )

    return PolymarketTrade(
        transaction_hash=require_str(entry, "transactionHash", PROVIDER, context),
        proxy_wallet=require_str(entry, "proxyWallet", PROVIDER, context),
        asset=require_str(entry, "asset", PROVIDER, context),
        side=side,
        condition_id=require_str(entry, "conditionId", PROVIDER, context),
        outcome=optional_str(entry.get("outcome"), PROVIDER, f"{context}.outcome"),
        outcome_index=optional_int(
            entry.get("outcomeIndex"), PROVIDER, f"{context}.outcomeIndex"
        ),
        price=price,
        size=size,
        traded_at=_epoch_seconds(entry.get("timestamp"), f"{context}.timestamp"),
        title=optional_str(entry.get("title"), PROVIDER, f"{context}.title"),
        slug=optional_str(entry.get("slug"), PROVIDER, f"{context}.slug"),
        event_slug=optional_str(entry.get("eventSlug"), PROVIDER, f"{context}.eventSlug"),
        captured_at=captured_at,
    )


def _epoch_seconds(value: object, context: str) -> datetime:
    """Unix SECONDS -> aware UTC datetime.

    Seconds, not milliseconds -- confirmed against a known trade
    (1780370221 -> 2026-06-02T03:17:01Z, matching that market's close). A
    millisecond reading would land in the year 58,000 and, because nothing
    downstream range-checks dates, would quietly file every trade past any
    as-of boundary a backtest could set.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ProviderValidationError(
            PROVIDER, f"timestamp must be a number, got {type(value).__name__}", context=context
        )
    try:
        seconds = int(value)
    except ValueError as exc:
        raise ProviderValidationError(
            PROVIDER, f"timestamp is not an integer: {value!r}", context=context
        ) from exc
    if seconds <= 0:
        raise ProviderValidationError(
            PROVIDER, f"timestamp must be positive, got {seconds}", context=context
        )
    return datetime.fromtimestamp(seconds, UTC)
