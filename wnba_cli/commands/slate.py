"""`wnba-cli slate` -- context for a whole day's games in one call."""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def slate() -> None:
    """A day's games: context plus the most divergent props."""


@slate.command("show")
@click.option("--game-ids", required=True, help="Comma-separated game ids, one day's worth.")
@click.option(
    "--limit", type=int, help="Top divergent props to include; API default if omitted."
)
def show(game_ids: str, limit: int | None) -> None:
    """Context for every game on a slate, plus the day's most divergent props."""
    emit(get("/slate", {"game_ids": game_ids, "limit": limit}))
