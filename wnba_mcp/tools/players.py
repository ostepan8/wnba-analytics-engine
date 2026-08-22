"""Players tools -- mirrors wnba_cli/commands/players.py."""

from __future__ import annotations

from typing import Any, Literal

from wnba_cli.client import get
from wnba_mcp.app import mcp

PropType = Literal["points", "rebounds", "assists", "threes", "points_rebounds_assists"]


@mcp.tool()
def players_list(
    season: int | None = None, q: str | None = None, limit: int = 300
) -> dict[str, Any]:
    """Players who appeared in the season, ranked by scoring. q: name search."""
    return get("/players", {"season": season, "q": q, "limit": limit})


@mcp.tool()
def players_show(player_id: int, season: int | None = None) -> dict[str, Any]:
    """Profile, per-season averages, and a game log for one player.

    season restricts the game log only; profile/seasons are unaffected and
    default to every season if omitted.
    """
    return get(f"/players/{player_id}", {"season": season})


@mcp.tool()
def players_props(
    player_id: int,
    season: int | None = None,
    prop_type: PropType | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Closing prop lines against what the player actually did."""
    return get(
        f"/players/{player_id}/props",
        {"season": season, "prop_type": prop_type, "limit": limit},
    )
