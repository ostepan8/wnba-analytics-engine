# wnba-analytics-engine

An open, WNBA-only data and analytics engine — odds history, outcomes, and
box-score/player stats joined together as a foundation for insights, picks,
and visualizations.

Status: early — see [ROADMAP.md](./ROADMAP.md). Phase 1, the multi-source
data foundation, is essentially complete; Phase 2 is the rules-based
insights layer.

WNBA only, by design. This repo is the open-source data/analytics core; any
consumer-facing product built on top of it lives separately.

## Documentation

| Doc | What it answers |
|---|---|
| [ROADMAP.md](./ROADMAP.md) | Why this exists, what's in and out of scope |
| [DATA_INVENTORY.md](./DATA_INVENTORY.md) | What data is in the database, where each piece comes from, and what's deliberately missing |
| [FEATURE_ROADMAP.md](./FEATURE_ROADMAP.md) | Features the engine should support, what each needs, and its leakage hazard |
| [MODELING_FINDINGS.md](./MODELING_FINDINGS.md) | What has been tried against this data and what it returned — read before building a model |
| [AGENTS.md](./AGENTS.md) | How to work in this repo — conventions, landmines, and operational gotchas. Read before changing anything |

## Quick start

```bash
docker compose up -d          # Postgres on :5434
uv run wnba-engine migrate    # apply migrations
uv run pytest -q              # tests
uv run wnba-engine validate   # data-quality gate
uv run wnba-engine --help     # every ingest command
```

## Running it

The engine deploys to a single always-on host as three services — Postgres,
a scheduler that runs every ingest job, and a read-only HTTP API that also
serves an analytics page. See [AGENTS.md](./AGENTS.md#deployment) for the
commands and `deploy/` for the manifests.

| Path | What |
|---|---|
| `deploy/schedule.toml` | every recurring job and its cadence, in one file |
| `deploy/nephos/` | service manifests + the public route |
| `deploy/Dockerfile` | one image: CLI, scheduler, and API |

The API is read-only and unauthenticated by design — public WNBA data, no
write path, no credentials in the process. Endpoints: `/summary`,
`/games`, `/games/{id}/odds`, `/games/{id}/markets`, `/divergences`,
`/leaders`, `/health/jobs`, and OpenAPI docs at `/docs`.

## License

MIT — see [LICENSE](./LICENSE).
