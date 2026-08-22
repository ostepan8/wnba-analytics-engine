"""Stats tool -- mirrors wnba_cli/commands/stats.py."""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def stats_leaders(season: int | None = None, min_games: int = 5, limit: int = 25) -> dict[str, Any]:
    """Season per-game leaderboard, ranked by points. Defaults to the current year."""
    return get("/leaders", {"season": season, "min_games": min_games, "limit": limit})
