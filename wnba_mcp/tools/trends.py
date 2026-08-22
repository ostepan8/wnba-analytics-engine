"""Trends tool -- mirrors wnba_cli/commands/trends.py."""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def trends_defense_by_position(
    season: int | None = None, team_id: int | None = None
) -> dict[str, Any]:
    """What each team allows to each position, per opposing player-game.

    team_id restricts to one team's rows; omit for the league-wide ranked table.
    """
    return get("/defense/by-position", {"season": season, "team_id": team_id})
