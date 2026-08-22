"""Slate tool -- mirrors wnba_cli/commands/slate.py."""

from __future__ import annotations

from typing import Any

from wnba_cli.client import get
from wnba_mcp.app import mcp


@mcp.tool()
def slate_show(game_ids: str, limit: int | None = None) -> dict[str, Any]:
    """Context for every game on a day's slate, plus the most divergent props.

    game_ids: comma-separated game ids, one day's worth.
    limit: how many top divergent props to include; API default if omitted.
    """
    return get("/slate", {"game_ids": game_ids, "limit": limit})
