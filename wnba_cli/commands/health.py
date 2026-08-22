"""`wnba-cli health` -- liveness and pipeline-health."""

from __future__ import annotations

import click

from wnba_cli.client import get
from wnba_cli.output import emit


@click.group()
def health() -> None:
    """Liveness, and per-job last-run/last-success/failure status."""


@health.command("status")
def status() -> None:
    """Liveness plus a real database round-trip."""
    emit(get("/health"))


@health.command("jobs")
def jobs() -> None:
    """Last run, last success, and recent failure count for every scheduled job."""
    emit(get("/health/jobs"))
