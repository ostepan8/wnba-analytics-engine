# AGENTS.md

Working notes for AI agents (and humans) in this repository. Read this
before making changes; most of it is knowledge that cost real debugging to
acquire and is not obvious from the code.

`DATA_INVENTORY.md` is the map of *what data exists and why*. `ROADMAP.md`
is *why the project exists*. This file is *how to work here*.

---

## What this is

An open, **WNBA-only** data and analytics engine: sportsbook odds,
prediction-market prices, outcomes, box scores, and play-by-play joined
into one queryable dataset. Phase 1 (multi-source data foundation) is
essentially complete; Phase 2 is a rules-based insights layer.

Scope discipline matters here. Two non-goals in `ROADMAP.md` are load-
bearing and should not be quietly eroded:

- **Never place, facilitate, or execute bets or trades.** Prediction-market
  integration is read-only price ingestion. There are no trading endpoints
  in this codebase and none should be added.
- **ML-driven predictions come after the rules-based layer proves out.**
  Clean feature extraction serves both, so building it is fine; presenting
  it as "the model pipeline" is not.

---

## Quick start

```bash
docker compose up -d                 # Postgres on :5434 (also creates the test DB)
uv run wnba-engine migrate           # apply pending SQL migrations
uv run pytest -q                     # full suite (integration tests skip without Postgres)
uv run ruff check .                  # lint
uv run wnba-engine validate          # data-quality gate; exits non-zero on real problems
uv run wnba-engine --help            # every ingest command
uv run wnba-cli --help               # query the LIVE API (games, players, odds, job health) -- no DB needed
```

`.env` (gitignored) holds `WNBA_ENGINE_BALLDONTLIE_API_KEY` and
`WNBA_ENGINE_ODDS_API_KEY`. Kalshi, Polymarket, and ESPN need no
credentials.

`wnba-cli` and `wnba-engine` are two different tools: `wnba-cli` only
speaks HTTP to the public read-only API (`wnba_cli/`, no DB access, works
without `.env` or Postgres) and is the fast path for an agent that just
needs current data; `wnba-engine` (`wnba_engine/cli/`) is the ingest/ops
CLI with direct DB access. See the `wnba-cli` skill (`.claude/skills/`)
for the full command reference.

---

## Architecture

One package per provider, and a strict split between layers:

```
wnba_engine/
  <provider>/        client (HTTP) + parser (PURE, no DB) + matching helpers
  models/            frozen dataclasses -- the shapes parsers produce
  repositories/      SQL. All of it. Nothing else touches the database.
  pipeline/          orchestration: fetch -> parse -> resolve -> persist
  validation/        data-quality checks + individually-acknowledged violations
  features/          composable, point-in-time-guarded preprocessing (see its README)
  market_capture/    off-box capture of unrecoverable feeds, and replay
  cli/main.py        one command per ingest path
db/migrations/       numbered, append-only, heavily commented SQL
```

**Parsers must stay pure.** They take a payload and return models; they
never open a connection. Anything needing the database (resolving a player
name to an id) belongs in the pipeline layer. This is what makes captured
payloads replayable and parsers unit-testable without Postgres.

### Canonical identity

`teams`, `players`, and `games` have **our own ids**, not any provider's.
Every provider's ids resolve through `provider_entity_map`
`(provider, entity_type, external_id) -> internal_id`. Onboarding a new
source never means a new table.

**These ids are generated per-database.** A row written on another machine
carries ids that mean something different here. Any cross-machine data
movement must transfer *raw provider payloads* and re-resolve locally --
this is exactly why `market_capture/` records JSON rather than rows.

---

## Conventions

- **Frozen dataclasses everywhere.** `@dataclass(frozen=True, slots=True)`.
  Never mutate an input; return a new object. Pipelines thread state with
  `dataclasses.replace`.
- **Docstrings explain WHY, and cite evidence.** "Verified live", a
  migration filename, another module. The codebase is dense with them on
  purpose: nearly every non-obvious line exists because a provider did
  something surprising, and the next reader needs to know what.
- Use `--` rather than em-dashes in code comments and docstrings.
- Type annotations on every signature. `from __future__ import annotations`.
- Files 200-400 lines typical, 800 max. Prefer many small modules.
- Ruff clean, line length 100.

### Worktree workflow (required)

Every implementation task runs in a git worktree, never directly on `main`.
Many agents work in this repo concurrently, so isolation, keeping docs
current, and careful merge-back are not optional -- see the
`parallel-worktree-lifecycle` skill (`.claude/skills/`) for the full
mandatory procedure. Quick reference:

```bash
git worktree add -b wt/<kebab-task> .claude/worktrees/<kebab-task> main
cp .env .claude/worktrees/<kebab-task>/     # gitignored, needed for integration tests
# ... work, test, update AGENTS.md/skills for anything that changed, commit ...
git fetch origin main && git merge origin/main   # catch up before merging back -- other agents may have landed first
# resolve any conflicts (watch db/migrations/ numbering -- renumber, never share a number)
git checkout main && git merge --no-ff wt/<kebab-task> -m "merge: wt/<kebab-task> into main"
git worktree remove .claude/worktrees/<kebab-task> --force
git branch -d wt/<kebab-task>
```

Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`). Bodies
explain the why and record decisions a reviewer should be able to
challenge. No AI attribution trailers.

---

## Landmines

These have all bitten. Read before touching the relevant area.

### Idempotency: every append-only table needs a natural key

The convention is `UNIQUE(<external identity>, captured_at)` plus
`ON CONFLICT DO NOTHING`, and insert functions return **actual rowcount**,
not `len(rows)` -- so a re-ingested payload correctly reports 0.

`sportsbook_game_odds`, `sportsbook_player_prop_odds`,
`odds_api_game_scores`, `market_price_snapshots` (0022), and
`injury_reports` (0023) all follow it. **Two of those constraints were
missing until replay made re-ingestion possible and would have silently
doubled every row.** If you add an append-only table, add the constraint
with it.

Choose the key carefully: `injury_reports` is keyed on
`(source, player_id, captured_at)`, NOT `reported_at` -- the latter is when
the *injury* was reported, so it recurs in every daily snapshot and has
20,971 legitimate duplicates.

### `captured_at` must be injectable, never `now()`

Any ingest function that stamps observations takes
`captured_at: datetime | None = None`, defaulting to now. Replaying a
recorded payload MUST pass the file's real capture time. Hardcoding
`datetime.now()` silently rewrites history to claim every past observation
happened at ingest.

### Some feeds are unrecoverable -- but fewer than this file used to claim

This section previously said Kalshi and Polymarket prices were
current-state only with **no historical endpoint**, and that an unrecorded
observation was gone forever. That was wrong, and believing it caused a
14-day July 2026 outage to be written off as unrecoverable when most of it
could have been refetched. Corrected 2026-08-03, verified live:

| feed | recoverable? | how |
|---|---|---|
| Polymarket **fills** | **yes, fully** | `data-api.polymarket.com/trades?market=<conditionId>`, every fill back to 2024-09-20, paginated. `backfill-polymarket-trades`. |
| Polymarket **quotes** | ~30 days | `clob.polymarket.com/prices-history` is a rolling cache, NOT an archive -- a June market with $377k volume returns zero points. |
| Kalshi **OHLC bars** | **yes, to market creation** | `/series/{s}/markets/{t}/candlesticks`. `backfill-kalshi-candles`. |
| Kalshi/Polymarket **order books** | no | depth is never republished. |
| ESPN **injury report** | no | current-state only; see `backfill-injuries-wayback` for a partial archive. |

So the capture host still earns its keep -- it holds the order book and the
quote history that nothing republishes -- but it is no longer the only path
to prediction-market history, and a gap in it is no longer fatal.

Captures run every 30 minutes and replay here (`market_capture/`). Capture
and ingest now share a host and a filesystem (see **Deployment** below), so
there is no pull step to miss. There used to be: capture ran on one Mac,
ingest on another, joined by an hourly rsync, and that rsync stranded 189
files per provider on 2026-08-03 and another seven days' worth on
2026-08-10. When adding a provider, ask first whether its data is
recoverable later, and check rather than assume.

---

## Deployment

Everything runs on one always-on Linux node as nephos services
(`deploy/nephos/`). Nothing is scheduled on a laptop any more.

| Service | What it is |
|---|---|
| `wnba-postgres` | Postgres 16, named volume, loopback on :5434 |
| `wnba-scheduler` | every recurring job (`deploy/schedule.toml`) |
| `wnba-api` | read-only HTTP API + analytics page, public via Cloudflare Tunnel |

```bash
ssh <node>
cd ~/projects/wnba-analytics-engine
bash deploy/build.sh                     # images are NOT distributed; build on the node
nephos up ./deploy/nephos/postgres       # then scheduler, then api
systemctl --user restart nephos-wnba-api.service   # `nephos up` alone won't restart a
                                                   # running service onto a new image
```

**Read `db/migrations/0031_job_runs.sql` before changing how anything is
scheduled.** The pipeline's real failure mode is not a crash, it is jobs
silently not running: six launchd agents hardcoded a repo path, the repo
moved, and two exited 78 while three exited *0* on a
`[ -d "$PROJECT_DIR" ] || exit 0` guard. The database froze for a week and
nothing noticed. Data freshness is not a substitute for run records either
-- the off-season looks exactly like a dead scheduler.

Two rules fell out of that, and both are load-bearing:

- **Every run is recorded**, including failures, and `/health/jobs` reads it.
- **Free work never queues behind paid work.** `capture-odds-focused`
  (metered) and `refresh-venue-prices` (free) were steps in one job; when
  the-odds-api key was deactivated for non-payment, the free steps stopped
  too, for a week, for no reason.

### the-odds-api costs [markets] x [regions] per request

Not per request. `capture-odds-focused` fires every two minutes near tip-off
and asked for `h2h,spreads,totals` while the divergence log it feeds reads
only the moneyline columns -- 3 credits a fire for 1 credit of data, ~21,000
credits a season instead of ~7,000. It now passes `MONEYLINE_ONLY_MARKETS`.
The 2-hourly routine snapshot still takes all three; those columns matter to
the wider dataset and do not need a two-minute cadence.

### A fixed matcher does not repair rows already stored

`ON CONFLICT DO NOTHING` is what makes every ingest re-runnable, and it is
also why a re-ingest **cannot** correct a row it already has. Fix a matcher
and only rows written afterwards benefit.

Kalshi rewrote its market titles between 2026-07-13 and 2026-07-27 --
`"Indiana vs Phoenix winner?"` became `"Las Vegas vs Chicago women's Pro
Basketball game: Chicago wins?"` -- and both `kalshi/game_matching.py` and
`kalshi/team_market_matching.py` stopped resolving games. The KXWNBAGAME
match rate went from 31-34% to **0.0%**, and 18,042 rows were written
unlinked before anyone noticed, because an unparseable title and a market
we deliberately do not map produce the identical outcome: a NULL `game_id`.

`uv run wnba-engine relink-market-games` fills NULL `game_id` using the
current matchers, and never overwrites one that is already set. **Run it
after touching any matcher.** `scripts/backfill-prediction-markets.sh` ends
with it for that reason.

### Point-in-time correctness

Anything building features or backtests must not read the future:

| Source | Hazard |
|---|---|
| `team_standings` | **current-state upsert** -- reading it for a 2023 game returns today's standings. Use `team_standings_history` (append-only, `captured_at`). |
| `players.age`, `players.jersey_number` | mutable, refreshed on every re-ingestion. `height`/`weight`/`college` are safe. |
| `season_awards` | end-of-season ground truth. Never a feature. |
| Season aggregates | include the target game unless explicitly windowed backwards. |

Safe as-of anchors: `games.start_time`, and `captured_at` on
`market_price_snapshots`, `sportsbook_game_odds`,
`sportsbook_player_prop_odds`, `injury_reports`,
`team_standings_history`.

**Do not hand-roll this.** `wnba_engine/features/` enforces all of the
above -- `feature_repo` refuses the leaky tables/columns by name and
refuses any query without an `%(as_of)s` filter, and `LeakageGuard` runs
after every step. Read `wnba_engine/features/README.md` before adding
feature extraction anywhere else.

Two hazards that table does NOT cover, both found while building that
package and both worth knowing anywhere else you join time series:

- **"Latest snapshot at or before as_of" is still a leak.** Joined onto a
  full-season frame it gives a May game the standings as they stood in
  July. A snapshot join has to be per ROW, against that row's own
  `start_time`, not per frame.
- **`games` has no `result_known_at`.** `start_time` says when a game
  began, not when we learned the score, so a boundary shortly after
  tip-off can consume a final score nobody had. The features package
  works around it with a 4-hour completion margin; a real column would be
  better.

### Providers are inconsistent in specific, documented ways

- **bovada writes some player props "Last First"** ("Austin Shakira") while
  every other book uses "First Last" -- and inconsistently within a single
  response. Handled by an opt-in `allow_reversed` in
  `find_player_by_name`; opt-in because the same helper serves ESPN
  transactions, where a reversed retry would match free-text noise.
- **the-odds-api re-issues event ids mid-game.** An event id is NOT a
  durable game key; resolve through the crosswalk.
- **the-odds-api per-event historical calls 404** when the event wasn't
  listed at that timestamp. Routine at T-7d, not an error.
- **balldontlie issues different player ids for the same person** across
  its own endpoints.
- **ESPN's `gameInfo` sometimes omits `officials` entirely.** Fail open.
- Player names change (marriage, rebrand) and books misspell them. Fixed
  by the **exact, curated** `player_aliases.py` -- never by fuzzy matching.
  `"Collier N."` is deliberately unresolved because both Napheesa and
  Charli Collier exist.

### Vendor archive boundaries (permanent, do not "fix")

- the-odds-api featured markets start **May 2022**; the first ~2 weeks of
  the 2022 season have no odds and never will.
- Player props start **May 2023**.
- Preseason and All-Star games are largely unpriced by books -- filter to
  `season_type IN ('regular-season','post-season')` when measuring odds
  coverage, or you'll compute a meaningless gap.

---

## Validation

`uv run wnba-engine validate` runs 12 checks and exits non-zero on any
**unacknowledged** violation.

Known-benign violations are acknowledged individually in
`wnba_engine/validation/acknowledged.py`, with the evidence that cleared
them and the date. This is deliberately not a per-check "ignore" switch:

- The key encodes the actual **values**, so any change re-raises the failure.
- A *new* violation of an acknowledged check still fails.
- Acknowledged violations are still counted and printed, tagged `[ack]`.
- Entries matching nothing are reported as **stale** so the file can't rot.

If you make `validate` permanently red, you have broken it -- a gate that
is always failing teaches everyone to ignore it.

---

## Testing

- Unit tests need no database. Integration tests are marked
  `pytestmark = pytest.mark.integration` and skip gracefully without one.
- **Fixtures are trimmed from real live-captured payloads**, never
  hand-written. Trimming must preserve provider quirks -- e.g. the current
  event-odds response has no `last_update` on the bookmaker while the
  historical one does, and tests pin that asymmetry.
- Prefer tests that assert what still **fails**. The most valuable tests
  here are the ones proving a new problem isn't masked by a known one.

### Verify against reality before believing you're done

The strongest lesson from this repo's history: a small sample validates
plumbing, not correctness. A three-day sample of a props backfill passed;
the full run then hit a crash on player-less outcomes, untrimmed names,
and a name-alias problem that a sample never touched. **Run one full
season (or one complete real unit of work) before committing to a large
batch**, and probe the live API directly when diagnosing rather than
reasoning from the code alone.

---

## Operations

Recurring jobs run via macOS LaunchAgents, mirrored in `~/dotfiles/mac/`.

**They fail silently by design** -- every script no-ops when the project,
Postgres, or `.env` is absent, so `launchctl` reporting exit 0 means "ran
and did nothing" as often as "ran and ingested". Only `max(captured_at)`
proves data is arriving:

```bash
docker exec -i wnba-analytics-engine-postgres-1 psql -U wnba -d wnba_engine -c "
select 'market_price_snapshots' t, max(captured_at)::date from market_price_snapshots
union all select 'sportsbook_game_odds', max(captured_at)::date from sportsbook_game_odds
union all select 'injury_reports', max(reported_at)::date from injury_reports;"
```

The realistic cause of an outage is **Docker's VM disk filling up**, which
crash-loops Postgres (`could not write lock file: No space left on
device`). Keep `diskSizeMiB` generous in
`~/Library/Group Containers/group.com.docker/settings.json`; `Docker.raw`
is sparse, so headroom is nearly free until used.

When refreshing row counts, use `count(*)`, not
`pg_stat_user_tables.n_live_tup` -- those statistics reset to 0 after a
crash-recovery restart and will look alarming and mean nothing.

---

## Cost awareness

the-odds-api is metered and the historical endpoints are expensive:

| Call | Units |
|---|---|
| Current odds / props | 1 per market per region |
| Historical odds / props | **10x** that |

A five-market, four-checkpoint historical prop sweep is ~200 units per
game (~209k for 2023-present). `x-requests-remaining` in the response
header is the authority; pipelines also report `units_estimated`. Check
remaining quota before launching a multi-season backfill, and prefer one
season first.
