"""Shared payload-validation helpers used by every provider parser.

All boundary validation funnels through these functions so malformed
provider data always surfaces as ProviderValidationError with the provider
name and payload location attached — never a bare KeyError/ValueError.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from wnba_engine.errors import ProviderValidationError


def require(payload: Mapping[str, object], key: str, provider: str, context: str) -> object:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            provider, f"expected object, got {type(payload).__name__}", context=context
        )
    value = payload.get(key)
    if value is None:
        raise ProviderValidationError(provider, f"missing required key '{key}'", context=context)
    return value


def require_str(payload: Mapping[str, object], key: str, provider: str, context: str) -> str:
    value = require(payload, key, provider, context)
    if not isinstance(value, str) or not value.strip():
        raise ProviderValidationError(
            provider, f"key '{key}' must be a non-empty string", context=context
        )
    return value


def require_mapping(
    payload: Mapping[str, object], key: str, provider: str, context: str
) -> Mapping[str, object]:
    value = require(payload, key, provider, context)
    if not isinstance(value, Mapping):
        raise ProviderValidationError(
            provider, f"key '{key}' must be an object", context=context
        )
    return value


def require_sequence(
    payload: Mapping[str, object], key: str, provider: str, context: str
) -> Sequence[object]:
    value = require(payload, key, provider, context)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProviderValidationError(provider, f"key '{key}' must be a list", context=context)
    return value


def parse_int(value: object, provider: str, context: str) -> int:
    try:
        return int(str(value).strip().replace("+", ""))
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            provider, f"expected integer, got {value!r}", context=context
        ) from exc


def parse_float(value: object, provider: str, context: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            provider, f"expected number, got {value!r}", context=context
        ) from exc


def optional_float(value: object, provider: str, context: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_float(value, provider, context)


def optional_int(value: object, provider: str, context: str) -> int | None:
    """Like parse_int, but treats missing/blank/placeholder values as None.

    Some providers (observed on ESPN) use a placeholder like '--' for a stat
    on an entity that otherwise has real data, rather than omitting the key.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or set(text) <= {"-"}:
        return None
    return parse_int(value, provider, context)


def parse_datetime_utc(value: object, provider: str, context: str) -> datetime:
    """Parse an ISO-8601 timestamp (with 'Z' or offset) into aware UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ProviderValidationError(
            provider, f"expected ISO timestamp string, got {value!r}", context=context
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderValidationError(
            provider, f"invalid ISO timestamp {value!r}", context=context
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def optional_datetime_utc(value: object, provider: str, context: str) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_datetime_utc(value, provider, context)
