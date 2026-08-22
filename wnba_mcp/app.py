"""The shared MCPServer instance.

Split from server.py so every tools/<resource>.py module can `from
wnba_mcp.app import mcp` and decorate onto it at import time, without a
circular import against server.py (which imports the tools modules for
their registration side effect, then runs the server).
"""

from __future__ import annotations

from mcp.server import MCPServer

mcp = MCPServer("wnba")
