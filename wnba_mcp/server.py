"""wnba-mcp-server entry point.

Registers every tool (import for side effect) then serves over stdio --
the transport deepseek-harness's dsh-mcp-client (and most MCP hosts) spawn
a child process and speak by default. See wnba_mcp/app.py for why the
MCPServer instance and the tool registrations live in separate modules.
"""

from __future__ import annotations

from wnba_mcp import tools  # noqa: F401  (import registers every @mcp.tool())
from wnba_mcp.app import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
