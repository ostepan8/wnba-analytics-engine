"""`wnba-cli teams` -- wraps GET /teams and its sub-resources, including the
two (/betting, head-to-head) that live in lines.py/trends.py on the API
side. Grouped here by resource, same rationale as commands/games.py.
"""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def teams() -> None:
    """Teams: list, detail, defense, betting record, recent shot chart."""


@teams.command("list")
@click.option("--season", type=int, help="Defaults to the current year.")
def list_teams(season: int | None) -> None:
    """Franchises only, with this season's record."""
    emit(get("/teams", {"season": season}))


@teams.command("show")
@click.argument("team_id", type=int)
@click.option("--season", type=int, help="Defaults to the current year.")
def show(team_id: int, season: int | None) -> None:
    """Team detail: record/standing, roster, schedule."""
    emit(get(f"/teams/{team_id}", {"season": season}))


@teams.command("defense")
@click.argument("team_id", type=int)
@click.option("--season", type=int, help="Defaults to the current year.")
@click.option("--bin-size", type=int, default=20, show_default=True)
@click.option("--player-limit", type=int, default=15, show_default=True)
def defense(team_id: int, season: int | None, bin_size: int, player_limit: int) -> None:
    """Where opponents shoot against this team, how well they do, and who."""
    emit(
        get(
            f"/teams/{team_id}/defense",
            {"season": season, "bin_size": bin_size, "player_limit": player_limit},
        )
    )


@teams.command("betting")
@click.argument("team_id", type=int)
@click.option("--season", type=int, help="Defaults to the current year.")
def betting(team_id: int, season: int | None) -> None:
    """A team's record against the closing spread and total."""
    emit(get(f"/teams/{team_id}/betting", {"season": season}))


@teams.command("shots-recent")
@click.argument("team_id", type=int)
@click.option(
    "--last-n-games", type=int, default=5, show_default=True, help="1-20 most recent games."
)
@click.option("--bin-size", type=int, default=20, show_default=True)
def shots_recent(team_id: int, last_n_games: int, bin_size: int) -> None:
    """A team's shot chart windowed by recent games rather than by season."""
    emit(
        get(
            f"/teams/{team_id}/shots/recent",
            {"last_n_games": last_n_games, "bin_size": bin_size},
        )
    )


@teams.command("head-to-head")
@click.argument("team_a", type=int)
@click.argument("team_b", type=int)
@click.option("--limit", type=int, default=10, show_default=True)
@click.option("--before", help="Only meetings before this timestamp (ISO 8601).")
def head_to_head(team_a: int, team_b: int, limit: int, before: str | None) -> None:
    """Previous meetings between two teams, newest first."""
    emit(get(f"/teams/{team_a}/head-to-head/{team_b}", {"limit": limit, "before": before}))
