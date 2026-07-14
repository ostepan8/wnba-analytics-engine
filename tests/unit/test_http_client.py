"""Unit tests for shared HTTP plumbing, focused on redact_query_params --
the mechanism that keeps a query-param-auth provider's API key (e.g.
the-odds-api's `apiKey=`) out of logs and exception messages. Header-based
auth (every other provider in this repo) never reaches this code path at
all, since it's opt-in via JsonHttpClient(redact_query_param_keys=...).
"""

from __future__ import annotations

import logging

import httpx
import pytest

from wnba_engine.errors import ProviderRequestError
from wnba_engine.http_client import JsonHttpClient, redact_query_params

SECRET = "SUPERSECRETKEY123"


def test_redact_query_params_replaces_value():
    text = f"request to https://example.test/v1/thing?apiKey={SECRET} failed"
    result = redact_query_params(text, {"apiKey": SECRET}, frozenset({"apiKey"}))
    assert SECRET not in result
    assert "***REDACTED***" in result


def test_redact_query_params_noop_without_matching_keys():
    text = f"contains {SECRET}"
    assert redact_query_params(text, {"apiKey": SECRET}, frozenset()) == text


def test_redact_query_params_noop_without_params():
    text = "no secrets here"
    assert redact_query_params(text, None, frozenset({"apiKey"})) == text


def test_redact_query_params_ignores_keys_not_present():
    text = f"contains {SECRET}"
    assert redact_query_params(text, {"other": "value"}, frozenset({"apiKey"})) == text


def test_get_json_redacts_api_key_from_exception_and_log(monkeypatch, caplog):
    client = JsonHttpClient(
        provider="test_provider",
        base_url="https://example.test",
        timeout_seconds=1.0,
        min_request_interval_seconds=0.0,
        redact_query_param_keys=frozenset({"apiKey"}),
    )
    request = httpx.Request("GET", f"https://example.test/v1/thing?apiKey={SECRET}")
    response = httpx.Response(401, request=request, text="unauthorized")

    def fake_do_get(path: str, params: object) -> httpx.Response:
        raise httpx.HTTPStatusError(
            f"Client error '401 Unauthorized' for url "
            f"'https://example.test/v1/thing?apiKey={SECRET}'",
            request=request,
            response=response,
        )

    monkeypatch.setattr(client, "_do_get", fake_do_get)
    try:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ProviderRequestError) as exc_info:
                client.get_json("v1/thing", params={"apiKey": SECRET})
        assert SECRET not in str(exc_info.value)
        assert SECRET not in caplog.text
        assert "***REDACTED***" in caplog.text
    finally:
        client.close()


def test_get_json_without_redact_keys_leaves_other_params_untouched(monkeypatch, caplog):
    client = JsonHttpClient(
        provider="test_provider",
        base_url="https://example.test",
        timeout_seconds=1.0,
        min_request_interval_seconds=0.0,
    )
    request = httpx.Request("GET", "https://example.test/v1/thing?season=2024")
    response = httpx.Response(500, request=request, text="server error")

    def fake_do_get(path: str, params: object) -> httpx.Response:
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr(client, "_do_get", fake_do_get)
    try:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ProviderRequestError):
                client.get_json("v1/thing", params={"season": 2024})
        assert "season" in caplog.text
        assert "2024" in caplog.text
    finally:
        client.close()
