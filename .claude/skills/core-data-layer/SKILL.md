---
name: core-data-layer
description: Map of wnba_engine's core data/orchestration layer -- pipeline/, repositories/, models/, validation/, features/, db/, and db/migrations/. The strict layering rule, canonical-identity crosswalk, idempotency convention, and point-in-time (leakage) guard. Load when touching pipeline orchestration, writing SQL, adding a migration, or building feature/backtest code.
---

# Core data layer

The strict layering rule (from `AGENTS.md`, lived in code): provider
`client`+`parser` (see [[data-providers]]) → `models/` (frozen dataclasses
parsers produce) → `repositories/` (**all** SQL, nothing else touches the
DB) → `pipeline/` (orchestration: fetch → parse → resolve → persist) →
`validation/` (data-quality gate) and `features/` (point-in-time-guarded
read layer on top of repositories). Load [[parallel-worktree-lifecycle]]
before editing anything here.

## Packages

| Package | Purpose |
|---|---|
| `wnba_engine/pipeline/` (~35 files) | One module per ingest/report path: fetch via a provider client, parse via its parser, resolve via `entity_repo`, persist via `repositories`. Also cross-cutting jobs: `market_game_relink.py`, `name_resolution.py`, `clv_report.py`, `divergence_report.py`, `feature_build.py` |
| `wnba_engine/repositories/` (~25 modules) | All SQL, one module per data domain (`entity_repo`, `stats_repo`, `odds_repo`, `market_repo`, `feature_repo`, `job_runs_repo`, etc.). Pipelines and features call these; nothing else touches Postgres |
| `wnba_engine/models/` | Frozen, `slots=True` dataclasses -- the pure shapes parsers produce and repositories persist. No behavior beyond simple properties |
| `wnba_engine/validation/` | `wnba-engine validate`'s ~18 checks (crosswalk, consistency, bounds, franchise, market-history). `acknowledged.py` holds individually-keyed, evidence-backed exceptions |
| `wnba_engine/features/` | Composable, point-in-time-guarded feature extraction -- **not** a model pipeline. Has its own `README.md`; read it before adding feature extraction anywhere else |
| `wnba_engine/db/` | Infra only: `pool.py` (psycopg_pool wrapper) and `migrate.py` (migration runner). No business SQL here |
| `db/migrations/` | 37 numbered, append-only, heavily commented SQL files (`0001_canonical_entities.sql` → `0037_headshot_unavailable.sql`), applied in filename order, tracked in a `schema_versions` table |

## Canonical identity

`teams`, `players`, `games` have **our own ids**, generated per-database
(never transfer raw rows cross-machine -- only raw payloads, replayed
locally; see `market_capture/` in [[runtime-services]]).
`repositories/entity_repo.py` is the crosswalk: `provider_entity_map
(provider, entity_type, external_id) -> internal_id`, with
`resolve_or_create_*` functions that look up or create+map atomically
(`ON CONFLICT (provider, entity_type, external_id) DO NOTHING`), plus
best-effort matchers (`find_player_by_name` with diacritic folding and an
opt-in `allow_reversed` for bovada's "Last First" quirk).

## Idempotency convention

Every append-only table: `UNIQUE(<external identity or natural key>,
captured_at)` + `ON CONFLICT DO NOTHING` (or `DO UPDATE` for
mutable/refreshable rows like advanced_stats, standings, shot_zone).
Insert functions return **actual DB rowcount**, not `len(rows)`, so a
replayed payload correctly reports 0 new rows. `captured_at` is always an
injectable parameter defaulting to `now()` -- never hardcode it, or a
replayed historical payload silently claims a present-day observation
time. **If you add an append-only table, add the constraint with it** --
two were missing until replay made re-ingestion possible and would have
silently doubled every row.

`ON CONFLICT DO NOTHING` also means **a fixed matcher cannot repair rows
already stored** -- re-run the relevant backfill/relink command (e.g.
`relink-market-games`) after fixing matching logic.

## Point-in-time correctness (`features/`)

`FeatureContext` carries a timezone-aware `as_of` boundary (naive
datetimes rejected in `__post_init__`). A `Pipeline` is an immutable tuple
of typed `Step`s (SOURCE/JOIN/TIME_INVARIANT/ROW_LOCAL/WINDOWED/FILTER/
FITTED); `LeakageGuard.check()` runs after **every** step -- not an
optional `run()` argument -- checking structure, provenance, the `as_of`
boundary, and window-end. `repositories/feature_repo.py` additionally
refuses raw SQL missing the literal `as_of` parameter, or referencing
forbidden identifiers by name: `team_standings` (current-state upsert --
reading it for a historical game returns today's standings; use
`team_standings_history`), `season_awards` (end-of-season ground truth,
never a feature), `players.age`/`players.jersey_number` (mutable,
refreshed on every re-ingest -- `height`/`weight`/`college` are safe).

Two hazards the guard does **not** cover:
- A "latest snapshot at or before `as_of`" join done across a whole frame
  is still a leak (attaches July standings to a May game) -- must be a
  per-row `AsOfJoinStep` against that row's own event time.
- `games` has no `result_known_at` column; `features/` approximates with a
  4-hour `completion_margin` after tip-off. A real fix would add the
  column.

`wnba_engine/features/steps/_windowing.py`'s `trailing_walk()` is the one
shared implementation every WINDOWED step uses, with same-instant-tie
handling so two rows sharing a timestamp can't enter each other's window.

## Other conventions worth knowing

- Frozen dataclasses everywhere; state threaded via `dataclasses.replace`,
  never mutated (matches this repo's global coding-style rule).
- Update-on-change idiom: `UPDATE ... WHERE id = ... AND col IS DISTINCT
  FROM new_value`, using `COALESCE` where a partial re-ingest shouldn't
  clobber a known-good value with NULL (see `update_game_venue_info`).
- `NUMERIC` columns arrive as `decimal.Decimal` in Python and raise
  `TypeError` against float arithmetic -- coerce before arithmetic in
  feature steps.
- Migrations are a flat, filename-sorted sequence with **no rollback
  mechanism**, append-only. See [[parallel-worktree-lifecycle]] for the
  concurrent-agent numbering-collision rule before adding one.
- No ORM -- raw parameterized SQL string constants per repository
  function. `features/` avoids pandas; frames are tuples of read-only
  mapping rows, with `to_columns()` bridging to pandas/polars if needed.
