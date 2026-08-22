"""wnba-cli -- an agent-facing CLI wrapper around the wnba-api's read-only
HTTP API. One subcommand group per resource; every command prints JSON to
stdout and a clean one-line error to stderr on failure (exit 1), so a
caller invoking this via a shell tool never has to parse a traceback or
remember the API's URL/query-param shape.

Base URL defaults to the public production API; override with
WNBA_CLI_BASE_URL (e.g. http://127.0.0.1:8090/api for a local dev API).
"""

from __future__ import annotations

import sys

import click

from wnba_cli.client import WnbaCliError
from wnba_cli.commands.games import games
from wnba_cli.commands.health import health
from wnba_cli.commands.lines import lines
from wnba_cli.commands.markets import markets
from wnba_cli.commands.players import players
from wnba_cli.commands.shooting import shooting
from wnba_cli.commands.slate import slate
from wnba_cli.commands.stats import stats
from wnba_cli.commands.teams import teams
from wnba_cli.commands.trends import trends


@click.group()
@click.option("--compact", is_flag=True, help="Single-line JSON instead of pretty-printed.")
@click.pass_context
def cli(ctx: click.Context, compact: bool) -> None:
    """Agent-facing CLI for the WNBA analytics engine's read-only API."""
    ctx.ensure_object(dict)
    ctx.obj["compact"] = compact


for _group in (games, health, lines, markets, players, shooting, slate, stats, teams, trends):
    cli.add_command(_group)


def main() -> None:
    try:
        cli(standalone_mode=False)
    except WnbaCliError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
