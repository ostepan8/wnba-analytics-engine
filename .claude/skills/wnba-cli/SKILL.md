---
name: wnba-cli
description: Use the wnba-cli command (uv run wnba-cli ...) to query the WNBA analytics engine's live data -- games, players, teams, standings, odds, props, divergences, job health -- instead of WebFetch/curl against the API or reading DB rows directly. Load whenever a task needs current game/player/team/market data from this project, or needs to check whether scheduled jobs are healthy.
---

# wnba-cli

An agent-facing CLI wrapper around the public, read-only `wnba-api`
(`https://wnba.onephos.com/api`). One subcommand group per resource,
output is JSON on stdout, errors are a clean one-line `error: ...` on
stderr with exit code 1 -- never a raw traceback. See [[runtime-services]]
for the API routes this wraps and [[codebase-map]] for the rest of the
repo.

**Prefer this over WebFetch/curl for anything this project's API already
serves.** It's faster to invoke correctly (no need to remember query-param
names or the base URL), and every command maps 1:1 to a documented route.

## Setup

Run from the repo root (or any worktree of it):
```bash
uv run wnba-cli --help
```
No install step beyond `uv sync` (already a core dependency -- `click`
and `httpx` are in `wnba-engine`'s base deps, not an optional extra).
Add `--compact` before the subcommand for single-line JSON when the
payload is large and pretty-printing would waste context:
```bash
uv run wnba-cli --compact games list --limit 5
```

`WNBA_CLI_BASE_URL` overrides the target API -- point it at
`http://127.0.0.1:8090/api` to hit a local dev server instead of
production.

## Command groups

| Group | Covers |
|---|---|
| `games` | list, show, odds, shots, props, box, flow, markets, zone-matchups, lines, trends, matchup -- everything about one game |
| `teams` | list, show, defense, betting, shots-recent, head-to-head |
| `players` | list, show, props |
| `markets` | summary, divergences, divergence-summary (cross-venue) |
| `shooting` | standings, shots (league-wide chart), efficiency |
| `lines` | closing (batch), market-props (live Kalshi/Polymarket props), props (league-wide rates) |
| `slate` | show -- one day's games with context, in one call |
| `stats` | leaders |
| `trends` | defense-by-position |
| `health` | status, jobs |

Run `uv run wnba-cli <group> --help` for exact flags -- every option
mirrors the underlying route's query parameter 1:1 (see
`wnba_engine/api/routes/*.py` if a flag's exact semantics matter and the
`--help` text isn't enough).

## Examples

```bash
# What's on tonight, with context
uv run wnba-cli games list --limit 10

# Everything about one game in one call (form, rest, betting, injuries)
uv run wnba-cli games matchup 1234

# A player's recent scoring vs their prop line
uv run wnba-cli players props 456 --prop-type points

# Is the pipeline actually healthy right now?
uv run wnba-cli health jobs
```

## What this does NOT do

- No write path -- the API it wraps has none (read-only by design, see
  ROADMAP.md non-goals). This CLI can't place or simulate a bet/trade.
- No direct DB access -- unlike `wnba-engine` (the ingest/ops CLI in
  `wnba_engine/cli/`), this talks only to the public HTTP API. Don't
  confuse the two; `wnba-engine` is for ingest/migrate/validate, this is
  for querying already-live data.
- Not a replacement for `ssh fedora` + a read-only SQL query when you need
  something the API doesn't expose (e.g. raw `job_runs` history beyond
  what `/health/jobs` summarizes) -- see the deploy-pipeline reference for
  that path.

**Wiring an external agent host (not this session) up to this data?** See
[[wnba-mcp-server]] instead -- same routes, exposed as MCP tools over
stdio rather than a shell command.

## Extending it

New API route → new command in `wnba_cli/commands/<group>.py` (create the
group file if it's a new resource), registered in `wnba_cli/main.py`.
Every command is a thin `emit(get(path, {params}))` call -- see any
existing command file for the pattern. Update this skill's table when you
add a group, per [[parallel-worktree-lifecycle]].
