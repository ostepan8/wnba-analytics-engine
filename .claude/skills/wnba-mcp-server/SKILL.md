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

**Confirmed working end-to-end** (2026-08-22): a real headless `dsh` run
called `health_status` and `games_matchup` through this mount against the
live production API and produced a correct answer, using a nephos-hosted
model instead of DeepSeek's own API. The deepseek-harness checkout lives
at `~/Desktop/Projects/deepseek-harness` (sibling project, not in this
repo -- see [[codebase-map]]); its config lives *outside* both git repos
at `~/.dsh/profiles/<profile>/cordis.patch.yml`, so it won't show up in
either repo's diff. This section is that recipe.

`@deepseek-ai/dsh-mcp-client` mounts stdio MCP servers as
`mcp__<serverName>__<tool>`. One id-targeted patch inserts the mount; two
more are required alongside it to actually reach a self-hosted
OpenAI-compatible endpoint (nephos) instead of DeepSeek's public API --
skipping either produces a real runtime error, not a silent fallback:

```yaml
# ~/.dsh/profiles/<profile>/cordis.patch.yml
- id: llm-deepseek
  config:
    baseURL: https://llm.onephos.com/v1   # or any OpenAI-compatible endpoint
    # llm-deepseek's default reasoningEffort ("high") isn't necessarily in
    # your backend's accepted vocabulary -- nephos's Qwen backend only
    # understands xhigh/medium/low and 400s on "high" with
    # INVALID_REQUEST: could not apply chat template. Confirm your
    # backend's actual vocabulary rather than assuming DeepSeek's.
    reasoningEffort: low
    models:                                # ADVISORY ONLY (picker UI) -- see below
      - id: fast
        name: "nephos: fast (Qwen3-4B)"
      - id: big
        name: "nephos: big (Qwen3.8-27B)"
- id: agent-default-model                  # THE actual default -- separate entry,
  config:                                  # easy to miss. Omitting this still
    provider: deepseek-official            # requests "deepseek-v4-flash" and 400s
    model: fast                            # with "unknown model" against an
                                            # alias-only backend like nephos.
- insert:
    - id: mcp-wnba
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: wnba
        transport: stdio
        command: uv
        args: ["run", "wnba-mcp-server"]
        env: {}
        cwd: /absolute/path/to/wnba-analytics-engine   # NOT !!js process.cwd() --
                                                         # dsh launches from the
                                                         # harness's own directory,
                                                         # not from this repo
```

The actual DeepSeek API key/secret goes in the harness project's own
`.env` (`DEEPSEEK_API_KEY=...`) -- but **`DEEPSEEK_BASE_URL` is refused
from `.env` entirely** ("only the launching environment may set it,"
since it decides where the process reaches over the network); set
`baseURL` in the config patch above instead, or `export` the env var in
the real shell if you need it outside a patched path.

For nephos specifically: `nephos models` / `nephos llm ls` lists the real
current aliases -- **"fast"/"big" are the alias contract, not real model
ids**, and whatever's actually loaded can be a completely different
family than the harness's branding suggests (confirmed live: nephos
currently serves Qwen3-4B and Qwen3.8-27B behind those aliases, zero
DeepSeek models). `nephos llm up <alias>` before testing if `nephos llm
ls` shows it `down`. Mint a scoped key with `nephos keys new
<app-name>` (omit `--models` for access to every alias) -- it's shown
once, store it in the harness's `.env`, not here.

The model then sees tools named `mcp__wnba__games_list`,
`mcp__wnba__games_matchup`, etc. -- one per function in `wnba_mcp/tools/`.
Verify with `dsh --profile headless --dump-config` (prints the fully
composed/patched config, confirms no patch silently no-op'd on a typo'd
`id`) before running a real prompt.

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
