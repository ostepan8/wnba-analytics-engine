"""Pure parser: Kalshi candlesticks JSON -> KalshiCandle.

Verified live on 2026-08-03 against
`/series/{series}/markets/{ticker}/candlesticks`. Response shape:

    {"ticker": "...", "candlesticks": [{
        "end_period_ts": 1785600000,
        "open_interest_fp": "2802.57",
        "volume_fp": "135.88",
        "price":   {"open_dollars","high_dollars","low_dollars",
                    "close_dollars","mean_dollars","previous_dollars"},
        "yes_bid": {"open_dollars","high_dollars","low_dollars","close_dollars"},
        "yes_ask": {"open_dollars","high_dollars","low_dollars","close_dollars"}
    }, ...]}

Two provider quirks are load-bearing:

- **Prices are dollar STRINGS**, not numbers ("0.1600"). The same trap
  `kalshi/parser.py` documents for the live snapshot feed: the legacy integer
  cent fields now come back null, and reading them gives a silent all-null
  column rather than an error.
- **A block can be absent entirely** on a bar where nothing traded. `price`
  missing means no print, which is different from a print at zero, so every
  field here is Optional and nothing is defaulted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.market_history import KalshiCandle
from wnba_engine.parsing import optional_float

PROVIDER = "kalshi"


def parse_candlesticks(
    payload: object,
    *,
    series_ticker: str,
    market_ticker: str,
    period_minutes: int,
    captured_at: datetime,
    title: str | None = None,
    context: str = "candlesticks",
) -> tuple[KalshiCandle, ...]:
    """Parse a candlesticks response.

    `market_ticker` is passed in rather than read from the response's own
    `ticker` field. The request already names the market, so trusting the
    caller keeps the parser pure and makes a mismatch impossible to
    introduce silently -- but the two are cross-checked below, because a
    mismatch would mean the endpoint served a different market than asked
    for and that is worth failing on rather than storing.
    """
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"candlesticks payload must be an object, got {type(payload).__name__}",
            context=context,
        )
    returned = payload.get("ticker")
    if isinstance(returned, str) and returned and returned != market_ticker:
        raise ProviderValidationError(
            PROVIDER,
            f"asked for {market_ticker!r} but response carries {returned!r}",
            context=context,
        )
    entries = payload.get("candlesticks")
    if entries is None:
        return ()
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, "candlesticks must be a list", context=context
        )
    return tuple(
        _parse_candle(
            entry, f"{context}[{i}]", series_ticker, market_ticker, period_minutes,
            captured_at, title,
        )
        for i, entry in enumerate(entries)
    )


def _parse_candle(
    entry: object,
    context: str,
    series_ticker: str,
    market_ticker: str,
    period_minutes: int,
    captured_at: datetime,
    title: str | None = None,
) -> KalshiCandle:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "candle must be an object", context=context)
    price = _block(entry.get("price"), f"{context}.price")
    bid = _block(entry.get("yes_bid"), f"{context}.yes_bid")
    ask = _block(entry.get("yes_ask"), f"{context}.yes_ask")
    return KalshiCandle(
        series_ticker=series_ticker,
        market_ticker=market_ticker,
        title=title,
        period_minutes=period_minutes,
        period_end=_epoch_seconds(entry.get("end_period_ts"), f"{context}.end_period_ts"),
        price_open=_dollars(price, "open_dollars", context),
        price_high=_dollars(price, "high_dollars", context),
        price_low=_dollars(price, "low_dollars", context),
        price_close=_dollars(price, "close_dollars", context),
        price_mean=_dollars(price, "mean_dollars", context),
        price_previous=_dollars(price, "previous_dollars", context),
        yes_bid_open=_dollars(bid, "open_dollars", context),
        yes_bid_high=_dollars(bid, "high_dollars", context),
        yes_bid_low=_dollars(bid, "low_dollars", context),
        yes_bid_close=_dollars(bid, "close_dollars", context),
        yes_ask_open=_dollars(ask, "open_dollars", context),
        yes_ask_high=_dollars(ask, "high_dollars", context),
        yes_ask_low=_dollars(ask, "low_dollars", context),
        yes_ask_close=_dollars(ask, "close_dollars", context),
        volume=optional_float(entry.get("volume_fp"), PROVIDER, f"{context}.volume_fp"),
        open_interest=optional_float(
            entry.get("open_interest_fp"), PROVIDER, f"{context}.open_interest_fp"
        ),
        captured_at=captured_at,
    )


def _block(value: object, context: str) -> Mapping[str, object]:
    """A price sub-object, or an empty mapping when the bar omits it."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"expected an object, got {type(value).__name__}", context=context
        )
    return value


def _dollars(block: Mapping[str, object], key: str, context: str) -> float | None:
    """One dollar-string field, validated as a probability.

    Kalshi contracts settle at $0 or $1, so a dollar price IS a probability
    and anything outside [0, 1] means the field is not what we think it is
    -- most likely the integer-cent field resurfacing, where "16" would
    otherwise be stored as a 1600% probability.
    """
    value = optional_float(block.get(key), PROVIDER, f"{context}.{key}")
    if value is None:
        return None
    if not 0.0 <= value <= 1.0:
        raise ProviderValidationError(
            PROVIDER, f"{key} must be a dollar price in [0, 1], got {value}", context=context
        )
    return value


def _epoch_seconds(value: object, context: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ProviderValidationError(
            PROVIDER,
            f"end_period_ts must be a number, got {type(value).__name__}",
            context=context,
        )
    try:
        seconds = int(value)
    except ValueError as exc:
        raise ProviderValidationError(
            PROVIDER, f"end_period_ts is not an integer: {value!r}", context=context
        ) from exc
    if seconds <= 0:
        raise ProviderValidationError(
            PROVIDER, f"end_period_ts must be positive, got {seconds}", context=context
        )
    return datetime.fromtimestamp(seconds, UTC)
