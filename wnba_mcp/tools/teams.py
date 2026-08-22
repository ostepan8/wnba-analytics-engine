"""Teams tools -- mirrors wnba_cli/commands/teams.py."""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def teams_list(season: int | None = None) -> dict[str, Any]:
    """Franchises only, with this season's record. Defaults to the current year."""
    return get("/teams", {"season": season})


@mcp.tool()
def teams_show(team_id: int, season: int | None = None) -> dict[str, Any]:
    """Team detail: record/standing, roster, schedule."""
    return get(f"/teams/{team_id}", {"season": season})


@mcp.tool()
def teams_defense(
    team_id: int, season: int | None = None, bin_size: int = 20, player_limit: int = 15
) -> dict[str, Any]:
    """Where opponents shoot against this team, how well they do, and who."""
    return get(
        f"/teams/{team_id}/defense",
        {"season": season, "bin_size": bin_size, "player_limit": player_limit},
    )


@mcp.tool()
def teams_betting(team_id: int, season: int | None = None) -> dict[str, Any]:
    """A team's record against the closing spread and total."""
    return get(f"/teams/{team_id}/betting", {"season": season})


@mcp.tool()
def teams_shots_recent(team_id: int, last_n_games: int = 5, bin_size: int = 20) -> dict[str, Any]:
    """A team's shot chart windowed by recent games (1-20) rather than by season."""
    return get(
        f"/teams/{team_id}/shots/recent", {"last_n_games": last_n_games, "bin_size": bin_size}
    )


@mcp.tool()
def teams_head_to_head(
    team_a: int, team_b: int, limit: int = 10, before: str | None = None
) -> dict[str, Any]:
    """Previous meetings between two teams, newest first.

    before: only meetings before this ISO 8601 timestamp -- pass a
    previewed game's tip-off to avoid that game's own result leaking in.
    """
    return get(f"/teams/{team_a}/head-to-head/{team_b}", {"limit": limit, "before": before})
