"""`wnba-cli trends` -- the one trends.py endpoint not scoped to a game or
a team pair (those live under `games`/`teams`): league-wide defense by
position.
"""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def trends() -> None:
    """League-wide defense-by-position."""


@trends.command("defense-by-position")
@click.option("--season", type=int, help="Defaults to the current year.")
@click.option("--team-id", type=int, help="Restrict to one team's rows.")
def defense_by_position(season: int | None, team_id: int | None) -> None:
    """What each team allows to each position, per opposing player-game."""
    emit(get("/defense/by-position", {"season": season, "team_id": team_id}))
