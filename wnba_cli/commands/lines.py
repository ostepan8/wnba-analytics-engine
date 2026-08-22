"""`wnba-cli lines` -- the sportsbook-lines endpoints that aren't scoped to
one game or team (those live under `games`/`teams`): closing lines for a
batch of games, live prediction-market props, and league-wide prop rates.
"""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def lines() -> None:
    """Batch closing lines, live market props, and league-wide prop rates."""


@lines.command("closing")
@click.option("--game-ids", required=True, help="Comma-separated game ids.")
def closing(game_ids: str) -> None:
    """Consensus closing spread, total and moneyline for a set of games."""
    emit(get("/lines/closing", {"game_ids": game_ids}))


@lines.command("market-props")
@click.option("--player-id", type=int)
@click.option("--game-id", type=int)
@click.option("--limit", type=int, default=300, show_default=True)
def market_props(player_id: int | None, game_id: int | None, limit: int) -> None:
    """Live player props from Kalshi and Polymarket."""
    emit(get("/lines/market-props", {"player_id": player_id, "game_id": game_id, "limit": limit}))


@lines.command("props")
@click.option("--season", type=int)
def props(season: int | None) -> None:
    """League-wide over/under rates by prop market."""
    emit(get("/lines/props", {"season": season}))
