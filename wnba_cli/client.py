"""Thin HTTP client for the wnba-api.

Deliberately no retry/backoff (unlike wnba_engine's ingest clients, which
use tenacity): this is an interactive, human-or-agent-in-the-loop tool
hitting idempotent GETs, and a hung retry loop is worse here than a clean
one-shot failure the caller can just re-run.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://wnba.onephos.com/api"
TIMEOUT_SECONDS = 15.0


class WnbaCliError(RuntimeError):
    """Raised for anything the CLI should report as a clean one-line stderr
    message rather than a raw traceback -- an agent invoking this via a
    shell tool needs `error: ...` on stderr and a non-zero exit, not a
    Python stack trace to parse."""


def base_url() -> str:
    """WNBA_CLI_BASE_URL overrides the public API, e.g. for a local dev
    server at http://127.0.0.1:8090/api."""
    return os.environ.get("WNBA_CLI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET {base_url}{path} and return the parsed JSON body.

    None-valued params are dropped rather than sent as the literal string
    "None" -- every optional CLI flag defaults to None and should behave
    exactly like omitting the query parameter.
    """
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    url = f"{base_url()}{path}"
    try:
        response = httpx.get(url, params=clean_params, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise WnbaCliError(f"request to {url} failed: {exc}") from exc
    if response.status_code >= 400:
        raise WnbaCliError(f"{response.status_code} from {url}: {response.text[:300]}")
    return response.json()
