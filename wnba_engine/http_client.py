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
        """
        self._provider = provider
        self._retryable_status_codes = retryable_status_codes
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
            logger.error(
                "request failed provider=%s url=%s params=%s error=%s",
                self._provider,
                url,
                params,
                exc,
            )
            raise ProviderRequestError(self._provider, url, str(exc)) from exc
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
            logger.error(
                "request failed provider=%s url=%s params=%s error=%s",
                self._provider,
                url,
                params,
                exc,
            )
            raise ProviderRequestError(self._provider, url, str(exc)) from exc
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

    def _is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in self._retryable_status_codes
        return False

    def _get_with_retry(
        self, path: str, params: Mapping[str, object] | None
    ) -> httpx.Response:
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
