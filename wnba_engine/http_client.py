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
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

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


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


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
    ) -> None:
        self._provider = provider
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

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=BACKOFF_MULTIPLIER_SECONDS, max=BACKOFF_MAX_SECONDS),
        reraise=True,
    )
    def _get_with_retry(
        self, path: str, params: Mapping[str, object] | None
    ) -> httpx.Response:
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
