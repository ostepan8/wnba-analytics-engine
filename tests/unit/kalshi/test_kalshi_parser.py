"""Unit tests for the Kalshi parser (pure, fixture-driven)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.kalshi.parser import (
    filter_wnba_series,
    parse_markets_page,
    parse_series_list,
)

CAPTURED_AT = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def test_parse_series_list(kalshi_series_payload):
    series = parse_series_list(kalshi_series_payload)
    assert len(series) == 5
    tickers = {s.ticker for s in series}
    assert "KXWNBAGAME" in tickers
    assert "KXNFLDSTTD" in tickers


def test_filter_wnba_series(kalshi_series_payload):
    series = parse_series_list(kalshi_series_payload)
    wnba = filter_wnba_series(series)
    assert {s.ticker for s in wnba} == {"KXWNBATOTAL", "KXWNBA", "KXWNBAGAME"}


def test_series_missing_ticker_raises(kalshi_series_payload):
    broken = copy.deepcopy(kalshi_series_payload)
    del broken["series"][0]["ticker"]
    with pytest.raises(ProviderValidationError, match="ticker"):
        parse_series_list(broken)


def test_parse_markets_page_snapshots(kalshi_markets_payload):
    snapshots, cursor = parse_markets_page(kalshi_markets_payload, captured_at=CAPTURED_AT)
    assert cursor  # fixture has a next-page cursor
    assert len(snapshots) == 3
    snap = snapshots[0]
    assert snap.provider == "kalshi"
    assert snap.market_external_id == "KXWNBAGAME-26JUL09INDPHX-PHX"
    assert snap.event_external_id == "KXWNBAGAME-26JUL09INDPHX"
    assert snap.title == "Indiana vs Phoenix winner?"
    assert snap.outcome == "Phoenix"
    assert snap.yes_bid == pytest.approx(0.40)
    assert snap.yes_ask == pytest.approx(0.41)
    assert snap.last_price == pytest.approx(0.41)
    # implied probability = mid of bid/ask when both quoted
    assert snap.implied_probability == pytest.approx(0.405)
    assert snap.volume == pytest.approx(1883.84)
    assert snap.status == "active"
    assert snap.close_time == datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    assert snap.captured_at == CAPTURED_AT


def test_implied_probability_falls_back_to_last_price(kalshi_markets_payload):
    payload = copy.deepcopy(kalshi_markets_payload)
    market = payload["markets"][0]
    market["yes_bid_dollars"] = None
    market["yes_ask_dollars"] = None
    snapshots, _ = parse_markets_page(payload, captured_at=CAPTURED_AT)
    assert snapshots[0].yes_bid is None
    assert snapshots[0].implied_probability == pytest.approx(0.41)


def test_market_missing_ticker_raises(kalshi_markets_payload):
    broken = copy.deepcopy(kalshi_markets_payload)
    del broken["markets"][0]["ticker"]
    with pytest.raises(ProviderValidationError, match="ticker"):
        parse_markets_page(broken, captured_at=CAPTURED_AT)


def test_malformed_price_raises(kalshi_markets_payload):
    broken = copy.deepcopy(kalshi_markets_payload)
    broken["markets"][0]["yes_bid_dollars"] = "not-a-price"
    with pytest.raises(ProviderValidationError, match="number"):
        parse_markets_page(broken, captured_at=CAPTURED_AT)


def test_out_of_range_probability_raises(kalshi_markets_payload):
    broken = copy.deepcopy(kalshi_markets_payload)
    broken["markets"][0]["yes_bid_dollars"] = "1.5000"
    with pytest.raises(ProviderValidationError, match="probability"):
        parse_markets_page(broken, captured_at=CAPTURED_AT)


def test_missing_markets_key_raises():
    with pytest.raises(ProviderValidationError, match="markets"):
        parse_markets_page({}, captured_at=CAPTURED_AT)
