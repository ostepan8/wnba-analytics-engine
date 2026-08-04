# Data Inventory

What's actually in this database, where each piece comes from, and how to
get more of it. Row counts below are a snapshot (see "How to refresh this
doc") — several pipelines run on a recurring schedule and grow these
numbers continuously; treat the counts as "order of magnitude as of last
update," not a live figure.

See `ROADMAP.md` for the why (breadth-as-moat, one adapter per provider,
canonical crosswalk). This doc is the what.

## Table of contents
- [Snapshot](#snapshot)
- [Coverage boundaries](#coverage-boundaries--whats-missing-and-why)
- [Sources at a glance](#sources-at-a-glance)
- [ESPN](#espn-free-public-site-api)
- [balldontlie.io](#balldontlieio-paid-goat-tier)
- [Manually curated reference data](#manually-curated-reference-data)
- [Kalshi](#kalshi-regulated-prediction-market)
- [Polymarket](#polymarket-prediction-market)
- [the-odds-api](#the-odds-api-paid-high-quota-plan)
- [Known but NOT integrated](#known-but-not-integrated)
- [Canonical schema & crosswalk](#canonical-schema--crosswalk)
- [Data quality / validation](#data-quality--validation)
- [Recurring ingestion schedule](#recurring-ingestion-schedule)
- [CLI command reference](#cli-command-reference)
- [How to refresh this doc](#how-to-refresh-this-doc)

---

## Snapshot

Real row counts as of 2026-08-04 (see bottom of this doc for the query
to get current numbers):

| Table | Rows | Table | Rows |
| `game_plays` | 978,128 | `game_officials` | 4,162 |
| `polymarket_trades` | 606,068 | `team_advanced_stats` | 2,572 |
| `kalshi_trades` | 550,958 | `games` | 1,377 |
| `market_price_snapshots` | 481,397 | `players` | 1,010 |
| `sportsbook_player_prop_odds` | 304,829 | `player_shot_zone_stats` | 880 |
| `shot_locations` | 164,143 | `player_transactions` | 600 |
| `kalshi_candlesticks` | 163,914 | `team_standings_history` | 205 |
| `sportsbook_game_odds` | 125,919 | `season_awards` | 129 |
| `player_game_stats` | 60,744 | `balldontlie_injury_reports` | 79 |
| `injury_reports` | 33,283 | `odds_api_game_scores` | 67 |
| `player_advanced_stats` | 28,995 | `team_shot_zone_stats` | 64 |
| `provider_entity_map` | 5,805 | `team_standings` | 64 |
| `team_game_stats` | 5,318 | `teams` | 28 (15 real franchises) |
