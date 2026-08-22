"""Shooting tools -- mirrors wnba_cli/commands/shooting.py."""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def shooting_standings(season: int | None = None) -> dict[str, Any]:
    """Standings with a real playoff seed, clinch status and magic number."""
    return get("/standings", {"season": season})


@mcp.tool()
def shooting_shots(
    season: int | None = None,
    player_id: int | None = None,
    team_id: int | None = None,
    bin_size: int = 20,
) -> dict[str, Any]:
    """League-wide (or filtered to one player/team) shot attempts and makes,
    binned onto a half-court grid."""
    return get(
        "/shots",
        {"season": season, "player_id": player_id, "team_id": team_id, "bin_size": bin_size},
    )


@mcp.tool()
def shooting_efficiency(
    season: int | None = None,
    min_games: int = 10,
    limit: int = 200,
    player_id: int | None = None,
) -> dict[str, Any]:
    """Usage rate against true shooting -- volume separated from value."""
    return get(
        "/efficiency",
        {"season": season, "min_games": min_games, "limit": limit, "player_id": player_id},
    )
