"""Pure parser: Kalshi historical trades JSON -> KalshiTrade.

Verified live on 2026-08-04 against `/historical/trades?ticker=...`.
Response is `{"trades": [...], "cursor": "..."}` with each record carrying:

    trade_id created_time ticker yes_price_dollars no_price_dollars
    count_fp taker_side taker_book_side taker_outcome_side is_block_trade

Prices are dollar STRINGS, the same trap `kalshi/parser.py` and
`kalshi/candle_parser.py` both document: the legacy integer-cent fields
come back null, so reading the wrong one yields a silent all-null column.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.market_history import KalshiTrade
from wnba_engine.parsing import optional_float, optional_str, parse_datetime_utc, require_str

PROVIDER = "kalshi"


def parse_trades(
    payload: object,
    *,
    captured_at: datetime,
    series_ticker: str | None = None,
    context: str = "historical/trades",
) -> tuple[tuple[KalshiTrade, ...], str | None]:
    """Parse one page of trades, returning them plus the next cursor."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"trades payload must be an object, got {type(payload).__name__}",
            context=context,
        )
    entries = payload.get("trades")
    if entries is None:
        return (), None
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ProviderValidationError(PROVIDER, "trades must be a list", context=context)
    trades = tuple(
        _parse_trade(entry, f"{context}[{i}]", captured_at, series_ticker)
        for i, entry in enumerate(entries)
    )
    cursor = payload.get("cursor")
    return trades, cursor if isinstance(cursor, str) and cursor else None


def _parse_trade(
    entry: object, context: str, captured_at: datetime, series_ticker: str | None
) -> KalshiTrade:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "trade must be an object", context=context)
    yes_price = optional_float(
        entry.get("yes_price_dollars"), PROVIDER, f"{context}.yes_price_dollars"
    )
    if yes_price is None:
        raise ProviderValidationError(
            PROVIDER, "trade has no yes_price_dollars", context=context
        )
    if not 0.0 <= yes_price <= 1.0:
        # A Kalshi contract settles at $0 or $1, so the dollar price IS a
        # probability. Out of range means the integer-cent field resurfaced.
        raise ProviderValidationError(
            PROVIDER, f"yes price must be in [0, 1], got {yes_price}", context=context
        )
    block = entry.get("is_block_trade")
    return KalshiTrade(
        trade_id=require_str(entry, "trade_id", PROVIDER, context),
        market_ticker=require_str(entry, "ticker", PROVIDER, context),
        series_ticker=series_ticker,
        yes_price=yes_price,
        no_price=optional_float(
            entry.get("no_price_dollars"), PROVIDER, f"{context}.no_price_dollars"
        ),
        size=optional_float(entry.get("count_fp"), PROVIDER, f"{context}.count_fp"),
        taker_side=optional_str(entry.get("taker_side"), PROVIDER, f"{context}.taker_side"),
        is_block_trade=bool(block) if isinstance(block, bool) else None,
        traded_at=parse_datetime_utc(
            entry.get("created_time"), PROVIDER, f"{context}.created_time"
        ),
        captured_at=captured_at,
    )
