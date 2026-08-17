"""A small OpenAI-compatible client for the local inference endpoint.

Points at nephos (`llm.onephos.com/v1`), which serves Owen's own hardware, so
calls are free and stay on his tailnet. Nothing here is specific to that: any
OpenAI-compatible base URL works.

Written against httpx directly rather than the `openai` package because this
needs one endpoint and one response field, and the ingest path must not gain a
heavyweight dependency to ask a four-billion-parameter model to pick a number.

Every failure returns None. An unreachable model must degrade to "unresolved",
which is exactly the behaviour the caller had before -- a scheduled ingest is
not allowed to fail because a GPU box is asleep.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0

# Temperature 0: this is a lookup, not a generation. The same name against the
# same candidates should decide the same way on every run, or the decision log
# is a record of dice rolls.
TEMPERATURE = 0.0


class LlmClient:
    """Minimal chat-completions caller."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        model: str = "fast",
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def __enter__(self) -> LlmClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def complete(self, prompt: str, *, max_tokens: int = 16) -> str | None:
        """The model's reply, or None if anything at all went wrong."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": TEMPERATURE,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as err:
            logger.warning("llm call failed: %s", err)
            return None

    @property
    def model(self) -> str:
        return self._model
