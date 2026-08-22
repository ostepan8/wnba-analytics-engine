"""`wnba-cli players` -- wraps GET /players and its sub-resources."""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def players() -> None:
    """Players: list, detail (profile/seasons/game log), prop history."""


@players.command("list")
@click.option("--season", type=int, help="Defaults to the current year.")
@click.option("--q", help="Name search.")
@click.option("--limit", type=int, default=300, show_default=True)
def list_players(season: int | None, q: str | None, limit: int) -> None:
    """Players who appeared in the season, ranked by scoring."""
    emit(get("/players", {"season": season, "q": q, "limit": limit}))


@players.command("show")
@click.argument("player_id", type=int)
@click.option("--season", type=int, help="Restricts the game log; profile/seasons are unaffected.")
def show(player_id: int, season: int | None) -> None:
    """Profile, per-season averages, and a game log."""
    emit(get(f"/players/{player_id}", {"season": season}))


@players.command("props")
@click.argument("player_id", type=int)
@click.option("--season", type=int)
@click.option(
    "--prop-type",
    type=click.Choice(("points", "rebounds", "assists", "threes", "points_rebounds_assists")),
)
@click.option("--limit", type=int, default=25, show_default=True)
def props(player_id: int, season: int | None, prop_type: str | None, limit: int) -> None:
    """Closing prop lines against what the player actually did."""
    emit(
        get(
            f"/players/{player_id}/props",
            {"season": season, "prop_type": prop_type, "limit": limit},
        )
    )
