"""Lines tools -- mirrors wnba_cli/commands/lines.py."""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def lines_closing(game_ids: str) -> dict[str, Any]:
    """Consensus closing spread, total and moneyline for a set of games.

    game_ids: comma-separated game ids.
    """
    return get("/lines/closing", {"game_ids": game_ids})


@mcp.tool()
def lines_market_props(
    player_id: int | None = None, game_id: int | None = None, limit: int = 300
) -> dict[str, Any]:
    """Live player props from Kalshi and Polymarket (the sportsbook prop feed is paid)."""
    return get("/lines/market-props", {"player_id": player_id, "game_id": game_id, "limit": limit})


@mcp.tool()
def lines_props(season: int | None = None) -> dict[str, Any]:
    """League-wide over/under hit rates by prop market."""
    return get("/lines/props", {"season": season})
