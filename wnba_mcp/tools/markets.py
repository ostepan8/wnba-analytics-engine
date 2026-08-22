"""Markets tools -- mirrors wnba_cli/commands/markets.py."""

from __future__ import annotations

from typing import Any, Literal

from wnba_cli.client import get
from wnba_mcp.app import mcp

Venue = Literal["polymarket", "kalshi"]


@mcp.tool()
def markets_summary() -> dict[str, Any]:
    """What is in the database, and how current it is."""
    return get("/summary")


@mcp.tool()
def markets_divergences(
    venue: Venue | None = None, graded_only: bool = False, limit: int = 100
) -> dict[str, Any]:
    """Individual cross-venue (prediction market vs sportsbook) divergence
    observations, newest first."""
    return get("/divergences", {"venue": venue, "graded_only": graded_only, "limit": limit})


@mcp.tool()
def markets_divergence_summary() -> dict[str, Any]:
    """Per-venue divergence aggregates, each rate reported with the count it came from."""
    return get("/divergences/summary")
