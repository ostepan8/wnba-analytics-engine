"""Unit tests for the data-api /trades parser.

Fixtures mirror a real response captured on 2026-08-03 from the Seattle
Storm vs. Dallas Wings market (conditionId 0x4f0c...), trimmed to the fields
the parser reads.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.polymarket.trade_parser import parse_trades

CAPTURED = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def _trade(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "proxyWallet": "0x6dab26eb9853b8bc7b9d91f622617fbd19a7e5c0",
        "side": "BUY",
        "asset": "68614306510668305271941478344805002277320598024963771652684192485488317993399",
        "conditionId": "0x4f0cc49d5b8e2ba8e7b33f200dc2a6150bf3511daa8558c39578d28c89772cd2",
        "size": 1000,
        "price": 0.001,
        "timestamp": 1780370221,
        "title": "Seattle Storm vs. Dallas Wings",
        "slug": "wnba-sea-dal-2026-06-01",
        "eventSlug": "wnba-sea-dal-2026-06-01",
        "outcome": "Seattle Storm",
        "outcomeIndex": 0,
        "transactionHash": "0x323a4af09271a8ebd3e838b3a4501f8fa8a9b54a858dab6e3969e5192f0be3e8",
    }
    return {**base, **overrides}


def test_a_fill_parses_with_its_outcome_named() -> None:
    """The outcome being STATED is the whole reason this table exists.

    market_price_snapshots has no recorded side for two-way game markets --
    Gamma leaves groupItemTitle null, so which team its probability refers
    to has to be inferred from title ordering. Here it is in the payload.
    """
    (trade,) = parse_trades([_trade()], captured_at=CAPTURED)
    assert trade.outcome == "Seattle Storm"
    assert trade.outcome_index == 0
    assert trade.side == "BUY"
    assert trade.price == 0.001
    assert trade.size == 1000


def test_the_timestamp_is_read_as_seconds_not_milliseconds() -> None:
    """1780370221 is 2026-06-02T03:17:01Z. Read as milliseconds it would be
    1970-01-21, and read the other way (a ms value taken as seconds) it
    lands past the year 58,000 -- neither is range-checked downstream, so a
    unit error would silently file every trade outside any as-of boundary.
    """
    (trade,) = parse_trades([_trade()], captured_at=CAPTURED)
    assert trade.traded_at == datetime(2026, 6, 2, 3, 17, 1, tzinfo=UTC)


def test_order_is_preserved_rather_than_normalised() -> None:
    """The endpoint returns newest-first and the caller paginates by offset.
    Re-sorting here would make a skipped page look like a clean series.
    """
    payload = [_trade(timestamp=1780370221), _trade(timestamp=1780370000)]
    trades = parse_trades(payload, captured_at=CAPTURED)
    assert [t.traded_at.timestamp() for t in trades] == [1780370221, 1780370000]


@pytest.mark.parametrize("bad_price", [-0.01, 1.01, 5])
def test_a_price_outside_zero_to_one_is_rejected(bad_price: float) -> None:
    """A Polymarket price IS a probability. Anything outside [0, 1] means
    the field is not what we think it is, and storing it would corrupt any
    de-vig or CLV computation reading this table.
    """
    with pytest.raises(ProviderValidationError):
        parse_trades([_trade(price=bad_price)], captured_at=CAPTURED)


def test_an_unknown_side_is_rejected() -> None:
    """side determines which way a fill moves implied probability, so a
    third value would silently invert any order-flow analysis.
    """
    with pytest.raises(ProviderValidationError):
        parse_trades([_trade(side="MINT")], captured_at=CAPTURED)


def test_a_negative_size_is_rejected() -> None:
    with pytest.raises(ProviderValidationError):
        parse_trades([_trade(size=-1)], captured_at=CAPTURED)


def test_an_empty_response_is_not_an_error() -> None:
    """A market that never traded returns []. That is the ordinary
    terminating condition for pagination, not a failure.
    """
    assert parse_trades([], captured_at=CAPTURED) == ()


def test_a_non_list_payload_is_rejected() -> None:
    with pytest.raises(ProviderValidationError):
        parse_trades({"trades": []}, captured_at=CAPTURED)


def test_profile_fields_are_not_carried_into_the_model() -> None:
    """Trader display identity is mutable personal data with no analytic
    use; keeping it would make an immutable-facts table mutable again.
    """
    (trade,) = parse_trades(
        [_trade(pseudonym="Incompatible-Pupa", bio="hello", profileImage="http://x")],
        captured_at=CAPTURED,
    )
    assert not hasattr(trade, "pseudonym")
    assert not hasattr(trade, "bio")
