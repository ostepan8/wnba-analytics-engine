---
name: wnba-mcp-server
description: How to run and wire up wnba-mcp-server -- an MCP server (wnba_mcp/) exposing the WNBA analytics engine's read-only API as tools for any MCP-capable agent host (e.g. deepseek-harness), over stdio. Load when connecting an external agent harness to this project's live data, or when adding/changing a tool this server exposes.
---

# wnba-mcp-server

An MCP server wrapping the exact same routes as [[wnba-cli]] (same
`wnba_cli.client.get()` calls, same process, no subprocess) but exposed as
MCP tools over stdio instead of CLI subcommands -- for mounting into an
MCP-capable agent host rather than invoking from a shell. See
[[runtime-services]] for the underlying API routes and
[[parallel-worktree-lifecycle]] before editing.

## Why this exists alongside wnba-cli, not instead of it

Two different consumers, two different protocols:
- **wnba-cli**: a human or an agent's shell tool invokes `uv run wnba-cli
  <group> <command>` directly and reads JSON on stdout.
- **wnba-mcp-server**: an MCP host (an agent harness) spawns this as a
  child process, speaks the MCP protocol over its stdin/stdout, and calls
  tools by name with a JSON-Schema-validated argument object -- no shell
  invocation, no argv parsing.

Both call `wnba_cli.client.get()` underneath. `wnba_mcp/tools/*.py`
deliberately mirrors `wnba_cli/commands/*.py`'s route coverage 1:1 as a
**separate** set of definitions rather than a shared registry -- click
needs CLI ergonomics (flags, `--help` text), MCP needs a JSON schema
derived from Python type hints via the `mcp` SDK's `@mcp.tool()`
decorator. Forcing one abstraction across both would cost more clarity
than it saves. If you add a route to one, add it to the other.

## Running it standalone (for testing)

```bash
uv sync --extra mcp
uv run wnba-mcp-server        # blocks, serves over stdio -- Ctrl-C to stop
```

More useful for verifying end-to-end without a full harness -- spawn it
as a real subprocess via the `mcp` SDK's own `Client`:
```python
import asyncio
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "wnba-mcp-server"])
    async with Client(stdio_client(params)) as client:
        print([t.name for t in (await client.list_tools()).tools])
        print((await client.call_tool("health_status", {})).structured_content)

asyncio.run(main())
```

## Wiring into deepseek-harness (or any MCP host with a stdio client plugin)

deepseek-harness's `@deepseek-ai/dsh-mcp-client` mounts stdio MCP servers
as `mcp__<serverName>__<tool>`. Config shape (adapt to whatever
patch/config mechanism the host uses):
```yaml
- insert:
    - id: wnba-mcp-server
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: wnba
        transport: stdio
        command: uv
        args: ["run", "wnba-mcp-server"]
        env: {}
        cwd: <absolute path to this repo>
```
The model then sees tools named `mcp__wnba__games_list`,
`mcp__wnba__games_matchup`, etc. -- one per function in `wnba_mcp/tools/`.

## Tool inventory

35 tools across the same 10 resource groups as [[wnba-cli]] (`games_*`,
`teams_*`, `players_*`, `markets_*`, `shooting_*`, `lines_*`, `slate_*`,
`stats_*`, `trends_*`, `health_*`). Names are flat (no MCP-native
namespacing within one server), so every tool is prefixed by its
resource to stay unique -- `games_list`, `games_show`, `teams_defense`,
etc. Run the `list_tools()` snippet above for the exact current set
rather than trusting a stale list here.

**Point any agent using this at `health_jobs` before trusting other
tools' data as current** -- the API stays up and answers queries even
when the ingest pipeline has been silently dead, per `health.py`'s own
module docstring in `wnba_engine/api/routes/`.

## Adding a new tool

1. Add the route to `wnba_cli/commands/<group>.py` first if it doesn't
   already exist there (keep the two in sync).
2. Add the matching `@mcp.tool()` function to `wnba_mcp/tools/<group>.py`
   -- same path/params as the CLI command, `get()` call, `dict[str, Any]`
   return, one-line docstring (becomes the tool's MCP description).
3. Update this skill's tool-inventory note if you add a new resource
   group (a new file under `wnba_mcp/tools/`), and register it in
   `wnba_mcp/tools/__init__.py`.
