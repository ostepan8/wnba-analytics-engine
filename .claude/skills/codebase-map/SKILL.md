---
name: codebase-map
description: Top-level map of the wnba-analytics-engine repo -- where every subsystem lives, how they connect, and which of the other .claude/skills/ to load for detail. Load this first when orienting in the repo, before deciding which files to read for an unfamiliar task.
---

# Codebase map

This is not a microservices repo -- it's a single Python package
(`wnba_engine`) organized by data provider, plus a separate frontend SPA,
shipped as **one container image** that runs as three nephos services
selected only by which command each service's manifest passes. Read
`AGENTS.md` at the repo root first; it is the canonical "how to work here"
doc. This skill and its siblings are a faster map into specific areas.

## The seven areas, and their skills

| Area | Skill | What's there |
|---|---|---|
| Data providers | [[data-providers]] | 7 packages (`balldontlie`, `espn`, `kalshi`, `odds_api`, `polymarket`, `wnba_official`, `wnba_stats`) -- each a client + pure parser + matching helpers for one external data source |
| Core data layer | [[core-data-layer]] | `pipeline/`, `repositories/`, `models/`, `validation/`, `features/`, `db/`, `db/migrations/` -- the strict fetch→parse→resolve→persist layering and point-in-time correctness machinery |
| Runtime services | [[runtime-services]] | `api/`, `scheduler/`, `cli/`, `market_capture/`, `backup/`, `analysis/`, `llm/`, plus `deploy/` (nephos manifests, Dockerfile, schedule.toml) |
| Frontend | [[frontend-app]] | `frontend/` -- Vite + React 19 + TypeScript SPA, hand-rolled data fetching, no state library |
| Ops & tooling | [[ops-and-tooling]] | `scripts/` (launchd agents on two machines), `tests/`, `docker-compose.yml`, `pyproject.toml` |
| Agent CLI | [[wnba-cli]] | `wnba_cli/` -- `uv run wnba-cli ...`, a query-only CLI wrapper around the live API, built for agents to reach for instead of WebFetch/curl |
| Agent MCP server | [[wnba-mcp-server]] | `wnba_mcp/` -- `uv run wnba-mcp-server`, the same routes as wnba-cli exposed as MCP tools over stdio, for mounting into an external agent host (e.g. deepseek-harness) |

Every task-lifecycle rule (worktrees, keeping docs current, merging) lives
in [[parallel-worktree-lifecycle]] -- load it before editing anything.
**Need live data (a game, a player, standings, job health) rather than
codebase structure?** Reach for [[wnba-cli]] instead of reading further --
it's faster than deriving the right endpoint from [[runtime-services]].

## One-paragraph architecture

Seven provider packages under `wnba_engine/` each expose a pure
`client.py` + `parser.py` (+ optional `*_matching.py`) for one external
data source. `wnba_engine/pipeline/` orchestrates fetch → parse → resolve
→ persist per provider, resolving every external id through the single
`provider_entity_map` crosswalk (`repositories/entity_repo.py`) so
`teams`/`players`/`games` carry **our own ids**, generated per-database.
`wnba_engine/repositories/` holds all SQL; nothing else touches Postgres.
`wnba_engine/features/` is a separate point-in-time-guarded read layer on
top of repositories, for building leakage-safe model features later.
`wnba_engine/validation/` is the data-quality gate (`wnba-engine
validate`). All of this ships as one container image
(`deploy/Dockerfile`) built on the target node and run three ways by
nephos: `wnba-postgres` (Postgres 16), `wnba-scheduler` (runs
`deploy/schedule.toml`'s jobs via the `wnba-engine` CLI), and `wnba-api`
(read-only FastAPI, also serves the built `frontend/` SPA as a static
fallback). `frontend/` talks only to same-origin `/api/*` routes.

## Fast orientation by task shape

- **"Add/fix a provider ingest"** → [[data-providers]] for the package's
  quirks, then [[core-data-layer]] for how `pipeline/` and
  `repositories/` expect to consume it. Check `AGENTS.md`'s Landmines
  section for that provider first -- most surprises are already documented.
- **"Add an API endpoint / touch a route"** → [[runtime-services]]
  (`wnba_engine/api/routes/`), then [[frontend-app]] if the frontend needs
  to consume it (`frontend/src/lib/api.ts` holds every response shape).
- **"Fix/build a frontend page or chart"** → [[frontend-app]] only; it's a
  self-contained SPA with no build-time coupling to Python beyond the
  `/api` contract.
- **"Change how something is scheduled / deployed"** → [[runtime-services]]
  (`deploy/schedule.toml`, `deploy/nephos/*/nephos.yaml`) plus
  [[ops-and-tooling]] if it's a launchd-managed job outside the container.
- **"Build a feature for modeling / backtesting"** → [[core-data-layer]],
  specifically `wnba_engine/features/README.md` and the `LeakageGuard`
  contract. Never hand-roll point-in-time joins.
- **"Add a migration"** → [[core-data-layer]] for the numbering/idempotency
  convention, and read `AGENTS.md`'s idempotency section before writing the
  `UNIQUE` constraint.

## Non-goals (load-bearing, don't erode)

- No trading/betting endpoints -- prediction-market integration is
  read-only price ingestion, enforced in both the API (no write routes)
  and the frontend copy ("read-only · price ingestion only, never order
  placement").
- ML-driven predictions come after the rules-based layer proves out;
  `wnba_engine/features/` is fine to build, presenting it as "the model"
  is not. `frontend/src/pages/Model.tsx` and anything
  auth/payments/ML/betting-shaped is treated as sensitive -- don't touch it
  casually.
