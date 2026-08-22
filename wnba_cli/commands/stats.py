"""`wnba-cli stats` -- season leaderboards."""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def stats() -> None:
    """Season per-game leaderboards."""


@stats.command("leaders")
@click.option("--season", type=int, help="Defaults to the current year.")
@click.option("--min-games", type=int, default=5, show_default=True)
@click.option("--limit", type=int, default=25, show_default=True)
def leaders(season: int | None, min_games: int, limit: int) -> None:
    """Season per-game averages, ranked by points."""
    emit(get("/leaders", {"season": season, "min_games": min_games, "limit": limit}))
