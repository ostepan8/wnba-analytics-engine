"""Output formatting.

Pretty JSON by default, single-line with --compact. There is no separate
human-table mode -- this CLI is agent-facing, and JSON is what an agent
parses most reliably either way.
"""

from __future__ import annotations

import json
from typing import Any

import click


def emit(data: Any) -> None:
    """Print an API response as JSON, respecting the top-level --compact flag."""
    root = click.get_current_context().find_root()
    compact = bool((root.obj or {}).get("compact", False))
    if compact:
        click.echo(json.dumps(data, separators=(",", ":"), default=str))
    else:
        click.echo(json.dumps(data, indent=2, default=str))
