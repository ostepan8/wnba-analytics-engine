"""Shared HTTP plumbing for provider clients.

One place for retry policy, rate limiting, timeouts, and error wrapping so
each adapter's client.py stays a thin list of endpoint methods.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from wnba_engine.errors import ProviderRequestError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
BACKOFF_MULTIPLIER_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 20.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
REDACTED = "***REDACTED***"


def redact_query_params(
    text: str, params: Mapping[str, object] | None, keys: frozenset[str]
) -> str:
    """Replace the literal value of any `keys` present in `params` wherever it
    appears in `text`.

    Some providers (the-odds-api) authenticate via a query-string parameter
    (`apiKey=...`) rather than a header. httpx embeds the full request URL --
    including query params -- in exception messages (e.g.
    HTTPStatusError.__str__), and JsonHttpClient also logs the `params`
    mapping directly on request failure. Header-based auth never appears in
    either place, so this is a no-op for every other provider (empty
    `keys`); it only matters for query-param-auth providers, which opt in
    via JsonHttpClient(redact_query_param_keys=...).
    """
    if not params or not keys:
        return text
    redacted = text
    for key in keys:
        value = params.get(key)
        if value:
            redacted = redacted.replace(str(value), REDACTED)
    return redacted


class RateLimiter:
    """Enforces a minimum interval between requests. Thread-safe.

    Deliberately stateful infrastructure (not domain data): it tracks the
    last request time behind a lock.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._min_interval - (now - self._last_request_at)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_request_at = time.monotonic()


class JsonHttpClient:
    """Rate-limited, retrying JSON GET client bound to one provider base URL."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        timeout_seconds: float,
        min_request_interval_seconds: float,
        headers: Mapping[str, str] | None = None,
        retryable_status_codes: frozenset[int] = RETRYABLE_STATUS_CODES,
        redact_query_param_keys: frozenset[str] = frozenset(),
    ) -> None:
        """retryable_status_codes overrides the default set for providers
        with unusual reliability characteristics -- e.g. archive.org's raw
        snapshot endpoint (WaybackClient) has been observed to intermittently
        403 on a snapshot the CDX index itself confirms was captured
        successfully (a serving-layer hiccup, not the permanent per-day 403
        that means ESPN blocked the original crawl). Treating 403 as
        retryable everywhere else would be wrong -- for most providers a 403
        means "not authorized," and retrying wastes calls without ever
        succeeding -- so this is opt-in per client, not a global change.

        redact_query_param_keys names any query params (e.g. "apiKey") whose
        values must never reach a log line or an exception message -- see
        redact_query_params(). Empty by default: most providers here
        authenticate via a header (never logged), not a query param.
        """
        self._provider = provider
        self._retryable_status_codes = retryable_status_codes
        self._redact_query_param_keys = redact_query_param_keys
        self._rate_limiter = RateLimiter(min_request_interval_seconds)
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers=dict(headers or {}),
            follow_redirects=True,
        )

    @property
    def provider(self) -> str:
        return self._provider

    def get_text(self, path: str, params: Mapping[str, object] | None = None) -> str:
        """GET a text/HTML document, retrying transient failures with backoff."""
        url = f"{self._client.base_url.join(path)}"
        try:
            response = self._get_with_retry(path, params)
        except httpx.HTTPError as exc:
            safe_params = self._redacted_params(params)
            safe_error = self._redact(str(exc), params)
            logger.error(
                "request failed provider=%s url=%s params=%s error=%s",
                self._provider,
                url,
                safe_params,
                safe_error,
            )
            raise ProviderRequestError(self._provider, url, safe_error) from exc
        return response.text

    def get_json(self, path: str, params: Mapping[str, object] | None = None) -> object:
        """GET a JSON document, retrying transient failures with backoff.

        Raises ProviderRequestError once retries are exhausted or on a
        non-retryable HTTP error.
        """
        url = f"{self._client.base_url.join(path)}"
        try:
            response = self._get_with_retry(path, params)
        except (httpx.HTTPError, ValueError) as exc:
            safe_params = self._redacted_params(params)
            safe_error = self._redact(str(exc), params)
            logger.error(
                "request failed provider=%s url=%s params=%s error=%s",
                self._provider,
                url,
                safe_params,
                safe_error,
            )
            raise ProviderRequestError(self._provider, url, safe_error) from exc
        try:
            return response.json()
        except ValueError as exc:
            logger.error(
                "non-JSON response provider=%s url=%s status=%s",
                self._provider,
                url,
                response.status_code,
            )
            raise ProviderRequestError(self._provider, url, f"invalid JSON body: {exc}") from exc

    def _redact(self, text: str, params: Mapping[str, object] | None) -> str:
        return redact_query_params(text, params, self._redact_query_param_keys)

    def _redacted_params(self, params: Mapping[str, object] | None) -> dict[str, object]:
        if not params:
            return {}
        return {
            key: (REDACTED if key in self._redact_query_param_keys else value)
            for key, value in params.items()
        }

    def _is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in self._retryable_status_codes
        return False

    def _get_with_retry(self, path: str, params: Mapping[str, object] | None) -> httpx.Response:
        # A Retrying instance built per call (not a class-level @retry
        # decorator) so the retry predicate can read this client's own
        # retryable_status_codes, which varies per provider.
        retrying = Retrying(
            retry=retry_if_exception(self._is_retryable),
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=BACKOFF_MULTIPLIER_SECONDS, max=BACKOFF_MAX_SECONDS),
            reraise=True,
        )
        return retrying(self._do_get, path, params)

    def _do_get(self, path: str, params: Mapping[str, object] | None) -> httpx.Response:
        self._rate_limiter.wait()
        response = self._client.get(path, params=dict(params or {}))
        response.raise_for_status()
        return response

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JsonHttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
