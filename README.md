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

## License

MIT — see [LICENSE](./LICENSE).
