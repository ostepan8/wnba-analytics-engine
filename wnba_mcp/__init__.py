"""wnba-mcp-server -- an MCP server exposing the WNBA analytics engine's
read-only API as tools for any MCP-capable agent host (e.g. deepseek-harness).

Wraps wnba_cli.client.get() directly (same process, no subprocess) -- this
package depends on wnba_cli, not the other way around. See wnba_cli/__init__.py
for why wnba_cli itself has no DB/wnba_engine dependency: the same reasoning
applies transitively here.
"""
