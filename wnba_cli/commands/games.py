"""`wnba-cli games` -- wraps GET /games and every /games/{id}/* sub-resource,
including the ones that live in lines.py/trends.py on the API side. Grouped
here by RESOURCE (a game) rather than by backend module, since that's how a
caller thinks about it: "everything about game X".
"""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def games() -> None:
    """Games: list, detail, odds, shots, props, box score, flow, markets."""


@games.command("list")
@click.option("--season", type=int, help="Season year, e.g. 2026.")
@click.option("--since", help="Only games starting on or after this date (YYYY-MM-DD).")
@click.option("--limit", type=int, default=50, show_default=True)
def list_games(season: int | None, since: str | None, limit: int) -> None:
    """Most recent games first, with team names and final scores."""
    emit(get("/games", {"season": season, "since": since, "limit": limit}))


@games.command("show")
@click.argument("game_id", type=int)
def show(game_id: int) -> None:
    """Full detail for one game."""
    emit(get(f"/games/{game_id}"))


@games.command("odds")
@click.argument("game_id", type=int)
@click.option("--limit", type=int, default=500, show_default=True)
def odds(game_id: int, limit: int) -> None:
    """Sportsbook line movement for one game, oldest first."""
    emit(get(f"/games/{game_id}/odds", {"limit": limit}))


@games.command("shots")
@click.argument("game_id", type=int)
@click.option("--team-id", type=int, help="One side only; omit for both.")
@click.option("--bin-size", type=int, default=25, show_default=True)
def shots(game_id: int, team_id: int | None, bin_size: int) -> None:
    """Shot locations for one game, binned, optionally for a single team."""
    emit(get(f"/games/{game_id}/shots", {"team_id": team_id, "bin_size": bin_size}))


@games.command("props")
@click.argument("game_id", type=int)
def props(game_id: int) -> None:
    """Player prop lines posted for this game, with what the player did."""
    emit(get(f"/games/{game_id}/props"))


@games.command("box")
@click.argument("game_id", type=int)
def box(game_id: int) -> None:
    """Per-player box score."""
    emit(get(f"/games/{game_id}/box"))


@games.command("flow")
@click.argument("game_id", type=int)
def flow(game_id: int) -> None:
    """Score margin through the game, one point per scoring play."""
    emit(get(f"/games/{game_id}/flow"))


@games.command("markets")
@click.argument("game_id", type=int)
@click.option("--limit", type=int, default=500, show_default=True)
def markets(game_id: int, limit: int) -> None:
    """Prediction-market implied probabilities for one game, both venues."""
    emit(get(f"/games/{game_id}/markets", {"limit": limit}))


@games.command("zone-matchups")
@click.argument("game_id", type=int)
def zone_matchups(game_id: int) -> None:
    """Rotation players on both sides with a real zone edge tonight."""
    emit(get(f"/games/{game_id}/zone-matchups"))


@games.command("lines")
@click.argument("game_id", type=int)
@click.option("--limit", type=int, default=500, show_default=True)
def lines(game_id: int, limit: int) -> None:
    """Every sportsbook quote recorded for one game, per book, oldest first."""
    emit(get(f"/games/{game_id}/lines", {"limit": limit}))


@games.command("trends")
@click.argument("game_id", type=int)
def trends(game_id: int) -> None:
    """Every live prop for this game, each with the player's record against it."""
    emit(get(f"/games/{game_id}/trends"))


@games.command("matchup")
@click.argument("game_id", type=int)
def matchup(game_id: int) -> None:
    """Both sides in one call: record, form, scoring, rest, betting, injuries."""
    emit(get(f"/games/{game_id}/matchup"))
