"""Unit tests for the Kalshi candlesticks parser.

Fixtures mirror a real response captured on 2026-08-03 from
KXWNBAGAME-26AUG02TORGS-TOR.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.kalshi.candle_parser import parse_candlesticks

CAPTURED = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)
TICKER = "KXWNBAGAME-26AUG02TORGS-TOR"


def _payload(candles: list[dict[str, object]] | None = None, **top: object) -> dict[str, object]:
    body: dict[str, object] = {"ticker": TICKER, "candlesticks": candles or [_candle()]}
    return {**body, **top}


def _candle(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "end_period_ts": 1785600000,
        "open_interest_fp": "2802.57",
        "volume_fp": "135.88",
        "price": {
            "open_dollars": "0.1600",
            "high_dollars": "0.1600",
            "low_dollars": "0.1600",
            "close_dollars": "0.1600",
            "mean_dollars": "0.1600",
            "previous_dollars": "0.1600",
        },
        "yes_bid": {
            "open_dollars": "0.1500",
            "high_dollars": "0.1500",
            "low_dollars": "0.1500",
            "close_dollars": "0.1500",
        },
        "yes_ask": {
            "open_dollars": "0.1600",
            "high_dollars": "0.1600",
            "low_dollars": "0.1600",
            "close_dollars": "0.1600",
        },
    }
    return {**base, **overrides}


def _parse(payload: object, period: int = 60):
    return parse_candlesticks(
        payload,
        series_ticker="KXWNBAGAME",
        market_ticker=TICKER,
        period_minutes=period,
        captured_at=CAPTURED,
    )


def test_dollar_strings_become_probabilities() -> None:
    """Kalshi quotes dollar STRINGS ("0.1600"), not numbers. The legacy
    integer-cent fields now come back null, so reading the wrong one gives
    a silent all-null column rather than an error.
    """
    (candle,) = _parse(_payload())
    assert candle.price_close == 0.16
    assert candle.yes_bid_close == 0.15
    assert candle.yes_ask_close == 0.16
    assert candle.volume == 135.88
    assert candle.open_interest == 2802.57


def test_bid_and_ask_are_kept_apart_from_the_traded_price() -> None:
    """Three separate series, not one. A bar can carry a quote with no
    trade at all, and collapsing to a midpoint destroys the spread -- which
    is the only way to tell a real quote from an empty book.
    """
    (candle,) = _parse(_payload())
    assert candle.yes_ask_close is not None and candle.yes_bid_close is not None
    assert candle.yes_ask_close - candle.yes_bid_close == pytest.approx(0.01)


def test_a_bar_with_no_trade_keeps_its_missing_price_null() -> None:
    """Kalshi omits the whole `price` block on a bar where nothing traded.
    Zero would be a claim the exchange never made.
    """
    (candle,) = _parse(_payload([_candle(price=None, volume_fp="0.00")]))
    assert candle.price_close is None
    assert candle.price_open is None
    assert candle.volume == 0.0
    assert candle.yes_bid_close == 0.15  # the quote still stands


def test_a_price_outside_zero_to_one_is_rejected() -> None:
    """Guards against the integer-cent field resurfacing: "16" would
    otherwise be stored as a 1600% probability.
    """
    with pytest.raises(ProviderValidationError):
        _parse(_payload([_candle(price={"close_dollars": "16"})]))


def test_a_response_for_a_different_market_is_rejected() -> None:
    """The request already names the market, so a mismatch means the API
    served something else -- worth failing on rather than storing under the
    ticker we asked for.
    """
    with pytest.raises(ProviderValidationError):
        _parse(_payload(ticker="KXWNBAGAME-26AUG02TORGS-GS"))


def test_a_missing_candlesticks_key_is_an_empty_result_not_an_error() -> None:
    """Routine for a window in which a market did not yet exist, and a
    backfill chunks blindly across such windows by design.
    """
    assert _parse({"ticker": TICKER}) == ()


def test_period_minutes_is_carried_through_because_it_is_part_of_the_key() -> None:
    """The same instant is legitimately covered by a 1-minute and a
    60-minute bar; storing both must not collide.
    """
    (hourly,) = _parse(_payload(), period=60)
    (minutely,) = _parse(_payload(), period=1)
    assert (hourly.period_minutes, minutely.period_minutes) == (60, 1)
    assert hourly.period_end == minutely.period_end == datetime(2026, 8, 1, 16, 0, tzinfo=UTC)


def test_a_non_object_payload_is_rejected() -> None:
    with pytest.raises(ProviderValidationError):
        _parse([_candle()])
