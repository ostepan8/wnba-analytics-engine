"""Engine-wide exception types.

Every provider adapter raises ProviderValidationError from its parser when a
raw API payload is malformed, and ProviderRequestError from its client when
the HTTP layer fails after retries. Callers never see raw KeyError/TypeError
from deep inside parsing code.
"""

from __future__ import annotations


class WnbaEngineError(Exception):
    """Base class for all engine errors."""


class ProviderValidationError(WnbaEngineError):
    """A provider returned a payload that failed validation/normalization.

    Carries enough context (provider + location in the payload) to debug
    without dumping the whole response.
    """

    def __init__(self, provider: str, message: str, *, context: str | None = None) -> None:
        self.provider = provider
        self.context = context
        detail = f"[{provider}] {message}"
        if context:
            detail = f"{detail} (at {context})"
        super().__init__(detail)


class ProviderRequestError(WnbaEngineError):
    """An HTTP request to a provider failed after retries were exhausted."""

    def __init__(self, provider: str, url: str, message: str) -> None:
        self.provider = provider
        self.url = url
        super().__init__(f"[{provider}] request to {url} failed: {message}")
