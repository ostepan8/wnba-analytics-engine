"""Games tools -- mirrors wnba_cli/commands/games.py's route coverage
exactly, just as MCP tools instead of click subcommands. Kept as a
separate, parallel definition rather than a shared registry: click needs
CLI ergonomics (flags/help text), MCP needs a JSON schema derived from
type hints -- different enough shapes that sharing code here would cost
more clarity than it saves.
"""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def games_list(
    season: int | None = None, since: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Most recent WNBA games first, with team names and final scores.

    since: only games starting on or after this date (YYYY-MM-DD).
    """
    return get("/games", {"season": season, "since": since, "limit": limit})


@mcp.tool()
def games_show(game_id: int) -> dict[str, Any]:
    """Full detail for one game."""
    return get(f"/games/{game_id}")


@mcp.tool()
def games_odds(game_id: int, limit: int = 500) -> dict[str, Any]:
    """Sportsbook line movement for one game, oldest first."""
    return get(f"/games/{game_id}/odds", {"limit": limit})


@mcp.tool()
def games_shots(game_id: int, team_id: int | None = None, bin_size: int = 25) -> dict[str, Any]:
    """Shot locations for one game, binned, optionally for a single team."""
    return get(f"/games/{game_id}/shots", {"team_id": team_id, "bin_size": bin_size})


@mcp.tool()
def games_props(game_id: int) -> dict[str, Any]:
    """Player prop lines posted for this game, with what the player did."""
    return get(f"/games/{game_id}/props")


@mcp.tool()
def games_box(game_id: int) -> dict[str, Any]:
    """Per-player box score for one game."""
    return get(f"/games/{game_id}/box")


@mcp.tool()
def games_flow(game_id: int) -> dict[str, Any]:
    """Score margin through the game, one point per scoring play."""
    return get(f"/games/{game_id}/flow")


@mcp.tool()
def games_markets(game_id: int, limit: int = 500) -> dict[str, Any]:
    """Prediction-market implied probabilities for one game, both venues."""
    return get(f"/games/{game_id}/markets", {"limit": limit})


@mcp.tool()
def games_zone_matchups(game_id: int) -> dict[str, Any]:
    """Rotation players on both sides with a real shot-zone edge tonight."""
    return get(f"/games/{game_id}/zone-matchups")


@mcp.tool()
def games_lines(game_id: int, limit: int = 500) -> dict[str, Any]:
    """Every sportsbook quote recorded for one game, per book, oldest first."""
    return get(f"/games/{game_id}/lines", {"limit": limit})


@mcp.tool()
def games_trends(game_id: int) -> dict[str, Any]:
    """Every live prop for this game, each with the player's record against it."""
    return get(f"/games/{game_id}/trends")


@mcp.tool()
def games_matchup(game_id: int) -> dict[str, Any]:
    """Both sides of a game in one call: record, form, scoring, rest,
    betting record, and the current injury report -- built for previewing
    a matchup before making a prediction."""
    return get(f"/games/{game_id}/matchup")
