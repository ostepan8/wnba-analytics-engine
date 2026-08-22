"""Importing this package registers every tool onto wnba_mcp.app.mcp --
each tools/<resource>.py module decorates its functions at import time via
`@mcp.tool()`. server.py imports this package once, for that side effect,
before calling mcp.run().
"""

from __future__ import annotations

from wnba_mcp.tools import (  # noqa: F401
    games,
    health,
    lines,
    markets,
    players,
    shooting,
    slate,
    stats,
    teams,
    trends,
)
