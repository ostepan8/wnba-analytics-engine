---
name: ops-and-tooling
description: Map of scripts/ (launchd-scheduled jobs across two machines), tests/ layout, docker-compose.yml, and pyproject.toml. Load when touching a launchd plist, adding a test, changing local Postgres setup, or editing package dependencies/entrypoints.
---

# Ops and tooling

The operational glue around `wnba_engine` that isn't part of the deployed
container -- see [[runtime-services]] for what *is* containerized and
nephos-managed. Load [[parallel-worktree-lifecycle]] before editing.

## `scripts/` -- a two-machine launchd pipeline

Recurring jobs run as macOS LaunchAgents (mirrored in `~/dotfiles/mac/`),
split across two machines:

1. **Capture host** (`mac-studio`, deployed via `deploy-capture-host.sh`):
   runs only `com.ostepan.wnba-market-capture.plist` every 30 min,
   invoking a deployed copy of `wnba_engine/market_capture/capture.py`
   (stdlib-only, no repo/uv/DB dependency).
2. **This laptop / main checkout** (installed via `install-market-sync.sh`):
   - `com.ostepan.wnba-market-sync.plist` (hourly): rsync-pulls captures,
     then `uv run wnba-engine ingest-market-captures` +
     `grade-divergences`.
   - `com.ostepan.wnba-odds-focused.plist` (every 2m): `capture-odds-focused`
     + `refresh-venue-prices` + `log-divergences`, gated to spend 0
     requests when no game is within 6h. **Must be installed from the
     main checkout, not a worktree** -- `install-market-sync.sh` hard-
     refuses to run from one, because the plist bakes in an absolute repo
     path and a deleted worktree silently breaks the agent for weeks
     (this already happened once).
3. **`backfill-prediction-markets.sh`** is the one script never scheduled
   by a plist -- deliberately manual/weekly since a full sweep takes ~1hr.
4. **`refresh-inventory-counts.py`** is standalone (run manually or in
   CI/pre-commit) -- rewrites `DATA_INVENTORY.md`'s row-count table from
   live `count(*)` queries.

### launchd gotchas baked into these scripts

- **TCC denies a launchd-spawned `/bin/zsh` read access to files under
  `~/Desktop`** (where this repo lives), even though `stat`/`ls` succeed --
  any script invoked directly from the repo by launchd silently exits
  127. Fix: stage scripts outside the repo (`~/wnba-market-capture/bin`)
  via `install-market-sync.sh`.
- **launchd hands jobs a minimal `PATH`** without `/opt/homebrew/bin`, so
  `uv` isn't found unless invoked via `/bin/zsh -lc` (login shell) rather
  than a bare script path -- both `wnba-market-sync` and `wnba-odds-focused`
  plists do this.
- Plists use `PLACEHOLDER_HOME`/`PLACEHOLDER_REPO` tokens that installer
  scripts `sed`-substitute at install time, since launchd doesn't expand
  `~` or env vars.

## `tests/`

Split `unit/` (13 files, no DB needed, some grouped in provider
subdirs like `tests/unit/kalshi`, `tests/unit/features`) vs `integration/`
(19 files, `pytestmark = pytest.mark.integration`, requires
`docker compose up -d`, prefixed/suffixed `_e2e`/`_ingest_e2e` for
pipeline tests). `tests/fixtures/` holds recorded API response
JSON/HTML, trimmed from real live-captured payloads (never hand-written --
trimming must preserve provider quirks, per `AGENTS.md`). `conftest.py` at
both levels supplies shared fixtures.

## `docker-compose.yml` and `db/init/`

Single `postgres:16-alpine` service, `wnba`/`wnba`/`wnba_engine` creds,
host port **5434** (not 5432, to avoid a system Postgres clash) →
container 5432, named volume `wnba_pgdata`, mounts `db/init` as
`docker-entrypoint-initdb.d`. `db/init/001-create-test-db.sql` creates a
separate `wnba_engine_test` DB once, so integration tests never touch the
dev DB.

## `pyproject.toml`

Hatchling-built package `wnba-engine`, Python ≥3.11. Core deps: `httpx`,
`psycopg[binary,pool]`, `click`, `tenacity`, `python-dotenv`, `pypdf`.
Extras: `modeling` (scikit-learn, numpy), `api` (fastapi,
`uvicorn[standard]`), `assets` (boto3). Dev group: `pytest`,
`pytest-asyncio`, `ruff`. Single console-script entrypoint:
`wnba-engine = "wnba_engine.cli.main:cli"`. Package manager is `uv`
throughout -- every script invokes `uv run wnba-engine ...` /
`uv run python ...`.

## `.env.example`

Three env vars, all optional/defaulted: `WNBA_ENGINE_DATABASE_URL`
(defaults to local docker-compose Postgres), `WNBA_ENGINE_KALSHI_API_KEY`
(Kalshi is readable without one today), `WNBA_ENGINE_BALLDONTLIE_API_KEY`
(**required** -- paid API, no anonymous tier).
