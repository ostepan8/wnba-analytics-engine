"""Health tools -- mirrors wnba_cli/commands/health.py.

An agent should check health_jobs before treating any other tool's data as
current -- see AGENTS.md's health.py module docstring: the API stays up
and answers queries even when the ingest pipeline has been silently dead
for a week.
"""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def health_status() -> dict[str, Any]:
    """Liveness plus a real database round-trip."""
    return get("/health")


@mcp.tool()
def health_jobs() -> dict[str, Any]:
    """Last run, last success, and recent failure count for every scheduled
    ingest job -- check this before trusting that other tools' data is
    fresh, not just that the API responded."""
    return get("/health/jobs")
