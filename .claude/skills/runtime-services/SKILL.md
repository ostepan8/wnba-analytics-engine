---
name: runtime-services
description: Map of the runtime/operational packages -- wnba_engine/api, scheduler, cli, market_capture, backup, analysis, llm -- and deploy/ (Dockerfile, schedule.toml, nephos manifests). How the API routes, the scheduler, and the three nephos services (wnba-postgres/wnba-scheduler/wnba-api) fit together. Load when adding an API endpoint, changing what's scheduled, or touching deployment.
---

# Runtime services

One Python package (`wnba_engine`), shipped as **one container image**
(`deploy/Dockerfile`), run three ways by nephos purely via each service
manifest's `command:`. See [[core-data-layer]] for what these packages sit
on top of, and [[parallel-worktree-lifecycle]] before editing.

## The three services

| nephos service | Image role | Command | Holds provider secrets? |
|---|---|---|---|
| `wnba-postgres` | Postgres 16 (`postgres:16-alpine`) | -- | no |
| `wnba-scheduler` | Runs `deploy/schedule.toml`'s jobs | `python -m wnba_engine.scheduler` | **yes** -- the only service that does |
| `wnba-api` | Read-only HTTP API + serves the built frontend | `uvicorn wnba_engine.api.app:app` | no -- DB URL only |

All three use `network: host` to reach `wnba-postgres`'s loopback-only
port 5434 (rootless Podman's pasta networking can't otherwise reach host
loopback). The image is built **on the target node** via `deploy/build.sh`
(podman, not a registry) -- nephos doesn't distribute images; a
`systemctl --user restart nephos-wnba-<svc>.service` is required after
`nephos up` to actually pick up a new image on an already-running service.

## `wnba_engine/api/`

`app.py`'s `create_app()` includes every router in `api/routes/` under
`API_PREFIX="/api"` **before** mounting the built `frontend/` SPA as a
static fallback at `/` -- route-matching must win over the mount, or a
frontend route like `/players/36` collides with an API path shape.
`deps.py`'s `lifespan()` opens a psycopg pool (min 1/max 8); every request
connection is marked `read_only = True` as defense in depth on top of the
app having no write routes at all. CORS is wide open by design (public,
unauthenticated, read-only data). Cache-Control varies per-route by data
volatility (finished games/closing lines get long TTLs; live data short).

| Route file | Serves |
|---|---|
| `health.py` | `/api/health`, `/api/health/jobs` (per-job last-run status, joined against `schedule.toml` so "never ran" vs "disabled on purpose" vs "silently dead" are distinguishable) |
| `markets.py` | `/api/summary`, `/api/divergences[/summary]` -- cross-venue divergence log |
| `directory.py` | `/api/teams`, `/api/players` index + detail, playoff seeding |
| `games.py` | `/api/games` + per-game odds/shots/props/box/flow/markets/zone-matchups |
| `stats.py` | `/api/leaders` |
| `shooting.py` | `/api/standings`, `/api/shots`, `/api/efficiency` |
| `lines.py` | Sportsbook line history/closing numbers |
| `trends.py` | Prop-line + historical hit-rate frequency, head-to-head |
| `slate.py` | `/api/slate` -- a full day of games in one request |

## `wnba_engine/scheduler/`

Data-driven, not code-driven: `config.py` parses `deploy/schedule.toml`
into frozen `Job`/`Trigger` dataclasses, resolving `{season}`/`{today}`/
`{days_ago:N}`/`{env:NAME}` placeholders **at fire time**. `runner.py` runs
one asyncio task per enabled job under a `TaskGroup` -- no shared queue,
jobs never overlap themselves, every fire records a `job_runs` row
(ok/failed/timeout, best-effort, never blocks the actual work) via
`repositories/job_runs_repo.py`. Steps are subprocesses (either
`python -m wnba_engine.market_capture.capture` or a `wnba-engine
<subcommand>`), each with a per-job timeout that **kills** (not
terminates) an overrunning command.

`deploy/schedule.toml` currently has ~9 jobs, notably: `market-capture`
(30m), `capture-ingest` (1h), `venue-prices` (2m, free), `odds-focused`
(2m, **currently disabled** -- budget exhausted), `espn-sync` (daily),
`db-backup` (daily 06:00). Don't assume a job listed here is actually
running -- check `/api/health/jobs` or `enabled =` in the toml.

## `wnba_engine/cli/`

`main.py` is a click group (`wnba-engine`) with ~45 subcommands -- these
are exactly the steps `schedule.toml` invokes, and also the human-run
one-off tool for backfills/ingests. Add a new provider or ingest path
here; see [[data-providers]] for that layer.

## `wnba_engine/market_capture/`, `backup/`, `analysis/`, `llm/`

- **`market_capture/capture.py`** is deliberately **stdlib-only** and
  imports nothing from `wnba_engine` -- it was designed to run standalone
  on a separate capture host with no repo/uv/DB. Keep that constraint if
  editing it. `replay.py` mirrors each provider's live pagination so
  `ingest-market-captures` runs recorded files through the real
  ingest/matching/persistence path.
- **`backup/database.py`**: nightly `pg_dump -Fc` to a `.partial` file
  then atomic rename, prunes beyond `--keep`. **Not off-site** -- same
  host/disk as Postgres.
- **`analysis/`**: pure derivation library (no I/O of its own) consumed by
  both API routes and CLI reports -- `clv.py`, `divergence.py`,
  `playoff_race.py`, `prop_trends.py`, `style.py`, `zone_matchups.py`.
- **`llm/`**: minimal OpenAI-compatible client (`client.py`) pointed at
  nephos's local inference endpoint, temperature 0, used as a lookup (name
  disambiguation in `name_resolver.py`) not a generator. Every failure
  returns `None` so ingest degrades to "unresolved" rather than crashing.

## `deploy/`

- **`Dockerfile`**: two-stage build -- stage 1 (node) builds `frontend/`
  into `wnba_engine/api/static/`; stage 2 (uv/python3.12) installs
  `postgresql-client-16` (**must exactly match** `wnba-postgres`'s major
  version or nightly backups fail loudly -- no apt fallback, a prior
  fallback silently installed v15 and broke backups).
- **`build.sh`**: `podman build --pull=newer`, run on the target node,
  smoke-tests the CLI/scheduler import and asserts `pg_dump` is v16.
- **`nephos/{postgres,scheduler,api}/nephos.yaml`**: the three service
  manifests. **`nephos up` alone does not restart a running service onto
  a new image** -- follow with `systemctl --user restart
  nephos-wnba-<svc>.service`.
- **`nephos/publish.yaml`**: Cloudflare Tunnel route
  `wnba.onephos.com -> 127.0.0.1:8090` for `wnba-api`, credentials via
  `vault get`, not stored in the manifest.

## Known-current operational state (verified live 2026-08-20; check before assuming otherwise)

- `odds-focused` scheduler job: disabled, the-odds-api credits near zero
  (~500 left). Sportsbook odds keep accruing via the 2-hourly routine
  snapshot regardless -- `latest_sportsbook_odds` is same-day fresh.
- ESPN `/injuries` 403s from mid-August self-resolved by 2026-08-20 with no
  code change; `market-capture` and `injury_reports(source='espn')` are
  both current. Don't assume a market-capture failure today is the same
  root cause -- check which provider actually failed.
- `balldontlie-season` and `image-sync` (weekly, Sunday) had never fired as
  of 2026-08-20 -- the scheduler container has only been up since
  2026-08-17, so no Sunday had occurred yet. Confirm they fired 2026-08-23;
  run their CLI commands manually first if shot zones/advanced stats/prop
  odds freshness matters sooner.
- Off-site backup is a real, still-open gap: nightly `pg_dump` lands on the
  same host/disk as Postgres. The intended Cloudflare R2 target rejects the
  TLS handshake with the credentials on file (see `deploy/schedule.toml`'s
  `db-backup` job comment).

This section will drift -- don't trust a date in it past a few weeks
without re-checking `/api/health/jobs` and the scheduler logs. If you fix
any of the above, update this line and the corresponding `AGENTS.md`/
`deploy/schedule.toml` note -- see [[parallel-worktree-lifecycle]].
