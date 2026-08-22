"""`wnba-cli markets` -- dataset summary and the cross-venue divergence log."""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def markets() -> None:
    """Dataset summary and prediction-market/sportsbook divergence."""


@markets.command("summary")
def summary() -> None:
    """What is in the database, and how current it is."""
    emit(get("/summary"))


@markets.command("divergences")
@click.option("--venue", type=click.Choice(("polymarket", "kalshi")))
@click.option("--graded-only", is_flag=True, help="Only observations that have been graded.")
@click.option("--limit", type=int, default=100, show_default=True)
def divergences(venue: str | None, graded_only: bool, limit: int) -> None:
    """Individual divergence observations, newest first."""
    emit(get("/divergences", {"venue": venue, "graded_only": graded_only, "limit": limit}))


@markets.command("divergence-summary")
def divergence_summary() -> None:
    """Per-venue aggregates, each rate reported alongside the count it came from."""
    emit(get("/divergences/summary"))
