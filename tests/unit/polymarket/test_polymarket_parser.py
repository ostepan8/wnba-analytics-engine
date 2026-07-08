"""Unit tests for the Polymarket Gamma parser (pure, fixture-driven)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.polymarket.parser import parse_events

CAPTURED_AT = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def test_parses_all_markets_across_events(polymarket_events_payload):
    snapshots = parse_events(polymarket_events_payload, captured_at=CAPTURED_AT)
    assert len(snapshots) == 6
    assert {s.provider for s in snapshots} == {"polymarket"}


def test_snapshot_fields(polymarket_events_payload):
    snapshots = parse_events(polymarket_events_payload, captured_at=CAPTURED_AT)
    atlanta = next(s for s in snapshots if s.market_external_id == "1892487")
    assert atlanta.event_external_id == "350828"
    assert atlanta.title == "Will Atlanta Dream win the 2026 WNBA Finals?"
    assert atlanta.outcome == "Atlanta Dream"
    assert atlanta.yes_bid == pytest.approx(0.12)
    assert atlanta.yes_ask == pytest.approx(0.13)
    assert atlanta.last_price == pytest.approx(0.13)
    # implied probability comes from outcomePrices[0] (the Yes price)
    assert atlanta.implied_probability == pytest.approx(0.125)
    assert atlanta.volume == pytest.approx(14637.117798, rel=1e-6)
    assert atlanta.liquidity == pytest.approx(17818.8242, rel=1e-6)
    assert atlanta.open_interest is None
    assert atlanta.status == "active"
    assert atlanta.close_time == datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
    assert atlanta.captured_at == CAPTURED_AT


def test_market_with_null_best_bid_still_parses(polymarket_events_payload):
    snapshots = parse_events(polymarket_events_payload, captured_at=CAPTURED_AT)
    sun = next(s for s in snapshots if s.market_external_id == "1892489")
    assert sun.yes_bid is None
    assert sun.implied_probability == pytest.approx(0.0005)


def test_implied_probability_falls_back_when_outcome_prices_missing(
    polymarket_events_payload,
):
    payload = copy.deepcopy(polymarket_events_payload)
    payload[0]["markets"][0]["outcomePrices"] = None
    snapshots = parse_events(payload, captured_at=CAPTURED_AT)
    atlanta = next(s for s in snapshots if s.market_external_id == "1892487")
    # falls back to bid/ask midpoint
    assert atlanta.implied_probability == pytest.approx(0.125)


def test_closed_market_status(polymarket_events_payload):
    payload = copy.deepcopy(polymarket_events_payload)
    payload[0]["markets"][0]["closed"] = True
    snapshots = parse_events(payload, captured_at=CAPTURED_AT)
    atlanta = next(s for s in snapshots if s.market_external_id == "1892487")
    assert atlanta.status == "closed"


def test_non_list_payload_raises():
    with pytest.raises(ProviderValidationError, match="list"):
        parse_events({"events": []}, captured_at=CAPTURED_AT)


def test_market_missing_question_raises(polymarket_events_payload):
    broken = copy.deepcopy(polymarket_events_payload)
    del broken[0]["markets"][0]["question"]
    with pytest.raises(ProviderValidationError, match="question"):
        parse_events(broken, captured_at=CAPTURED_AT)


def test_malformed_outcome_prices_json_raises(polymarket_events_payload):
    broken = copy.deepcopy(polymarket_events_payload)
    broken[0]["markets"][0]["outcomePrices"] = "{not json"
    with pytest.raises(ProviderValidationError, match="outcomePrices"):
        parse_events(broken, captured_at=CAPTURED_AT)


def test_out_of_range_probability_raises(polymarket_events_payload):
    broken = copy.deepcopy(polymarket_events_payload)
    broken[0]["markets"][0]["outcomePrices"] = '["1.5", "-0.5"]'
    with pytest.raises(ProviderValidationError, match="probability"):
        parse_events(broken, captured_at=CAPTURED_AT)
