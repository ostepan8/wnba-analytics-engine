"""Unit tests for shared payload-validation helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.parsing import (
    optional_datetime_utc,
    optional_float,
    parse_datetime_utc,
    parse_float,
    parse_int,
    require,
    require_sequence,
    require_str,
)


def test_require_returns_value():
    assert require({"a": 1}, "a", "p", "ctx") == 1


def test_require_missing_key_raises_with_context():
    with pytest.raises(ProviderValidationError) as excinfo:
        require({}, "a", "espn", "events[0]")
    assert "espn" in str(excinfo.value)
    assert "events[0]" in str(excinfo.value)


def test_require_str_rejects_blank():
    with pytest.raises(ProviderValidationError):
        require_str({"a": "  "}, "a", "p", "ctx")


def test_require_sequence_rejects_string():
    with pytest.raises(ProviderValidationError):
        require_sequence({"a": "abc"}, "a", "p", "ctx")


def test_parse_int_handles_plus_sign():
    assert parse_int("+8", "p", "ctx") == 8
    assert parse_int("-12", "p", "ctx") == -12


def test_parse_int_rejects_garbage():
    with pytest.raises(ProviderValidationError):
        parse_int("seventy", "p", "ctx")


def test_parse_float_from_dollar_string():
    assert parse_float("0.4100", "p", "ctx") == pytest.approx(0.41)


def test_optional_float_none_and_blank():
    assert optional_float(None, "p", "ctx") is None
    assert optional_float("", "p", "ctx") is None
    assert optional_float("1.5", "p", "ctx") == 1.5


def test_parse_datetime_z_suffix():
    parsed = parse_datetime_utc("2025-07-06T17:00Z", "p", "ctx")
    assert parsed == datetime(2025, 7, 6, 17, 0, tzinfo=UTC)


def test_parse_datetime_naive_assumed_utc():
    parsed = parse_datetime_utc("2026-10-31", "p", "ctx")
    assert parsed == datetime(2026, 10, 31, 0, 0, tzinfo=UTC)


def test_optional_datetime_none():
    assert optional_datetime_utc(None, "p", "ctx") is None


def test_parse_datetime_rejects_garbage():
    with pytest.raises(ProviderValidationError):
        parse_datetime_utc("not-a-date", "p", "ctx")
