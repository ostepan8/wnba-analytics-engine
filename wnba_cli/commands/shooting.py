"""`wnba-cli shooting` -- standings, league-wide shot charts, and
usage-vs-efficiency."""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def shooting() -> None:
    """Standings, shot charts, and usage-vs-efficiency."""


@shooting.command("standings")
@click.option("--season", type=int, help="Defaults to the current year.")
def standings(season: int | None) -> None:
    """Standings with a real playoff seed, clinch status and magic number."""
    emit(get("/standings", {"season": season}))


@shooting.command("shots")
@click.option("--season", type=int)
@click.option("--player-id", type=int)
@click.option("--team-id", type=int)
@click.option("--bin-size", type=int, default=20, show_default=True)
def shots(season: int | None, player_id: int | None, team_id: int | None, bin_size: int) -> None:
    """Shot attempts and makes, binned onto a half-court grid."""
    emit(
        get(
            "/shots",
            {"season": season, "player_id": player_id, "team_id": team_id, "bin_size": bin_size},
        )
    )


@shooting.command("efficiency")
@click.option("--season", type=int)
@click.option("--min-games", type=int, default=10, show_default=True)
@click.option("--limit", type=int, default=200, show_default=True)
@click.option("--player-id", type=int, help="Restrict to one player's row.")
def efficiency(season: int | None, min_games: int, limit: int, player_id: int | None) -> None:
    """Usage rate against true shooting -- volume separated from value."""
    emit(
        get(
            "/efficiency",
            {"season": season, "min_games": min_games, "limit": limit, "player_id": player_id},
        )
    )
