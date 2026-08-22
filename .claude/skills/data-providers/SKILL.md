---
name: data-providers
description: Map of the 7 external data-provider packages under wnba_engine/ (balldontlie, espn, kalshi, odds_api, polymarket, wnba_official, wnba_stats) -- what each source is, its client/parser/matching files, and provider-specific quirks. Load when touching any provider package, adding a new provider, or debugging an ingest/parsing/matching bug.
---

# Data providers

Seven packages live directly under `wnba_engine/`, one per external data
source. Every one follows the same shape: `client.py` (HTTP only) +
`*_parser.py` (pure functions, payload → frozen dataclass models, **never**
touch the DB) + optional `*_matching.py` (best-effort text/ticker parsing
that maps provider free text to a canonical entity -- still pure, no DB).
`wnba_engine/pipeline/<provider>_*_ingest.py` wires each provider in:
fetch (client) → parse (parser) → resolve (matching helpers +
`repositories/entity_repo.py`, through `provider_entity_map`) → persist
(`repositories/*_repo.py`). `wnba_engine/cli/main.py` exposes one command
per ingest path. See [[core-data-layer]] for the layers downstream of this
one, and [[parallel-worktree-lifecycle]] before editing.

## The seven packages

| Package | Source | Why it exists |
|---|---|---|
| `balldontlie` | balldontlie.com (paid, `WNBA_ENGINE_BALLDONTLIE_API_KEY`, no free tier) | Advanced per-player/team-per-game stats (offensive rating, PIE, four factors) unavailable elsewhere; also a 2nd independent box-score source vs ESPN, plays/pbp, shot-zone efficiency, standings, odds, prop odds, injuries, full player bios |
| `espn` | site.api.espn.com + web.archive.org | Scoreboard/boxscore/summary, current-state injuries, free-text transactions. Wayback snapshots of the injuries page are the **only** source of point-in-time historical injury status. `EspnClient(settings, league="nba")` also serves the NBA (confirmed live 2026-08-22, identical response shape) -- see NBA gotcha below |
| `kalshi` | api.elections.kalshi.com/trade-api/v2 (free, no key needed today) | Prediction-market snapshots, historical trades, OHLC candlesticks. Read-only, no trading endpoints |
| `odds_api` | the-odds-api.com (paid, metered, `WNBA_ENGINE_ODDS_API_KEY`) | Sportsbook moneyline/spread/total odds (current + historical), player prop odds, final scores |
| `polymarket` | gamma-api.polymarket.com (metadata/quote) + data-api.polymarket.com (fills) | Read-only prediction-market prices; two hosts with different mutability semantics |
| `wnba_official` | NBA CDN hourly injury-report PDF | The only source with real Probable/Questionable/Doubtful/Out granularity. `WnbaOfficialClient(league="nba")` reads `.../referee/nba_injury/...` instead -- confirmed reachable live 2026-08-22 (returns this CDN's real "no such file" 403 since the NBA season hasn't started, not a real error) |
| `wnba_stats` | stats.wnba.com (free, bot-detection-gated) | Same host family as stats.nba.com; `LeagueID=10` selects WNBA. `WnbaStatsClient(settings, league="nba")` selects `LeagueID=00`/stats.nba.com -- **not live-tested**, stats.nba.com was sandbox-network-blocked in every session so far (WNBA control failed identically) |

## Per-provider gotchas (pulled from code docstrings)

- **balldontlie**: fails fast at client construction if the key is
  missing (no anonymous tier). `/odds` returns only a rolling recent
  window, not history. `player_prop_odds` needs `game_id=`, not date
  ranges. Issues different player ids across its own endpoints (see
  `player_aliases.py` / AGENTS.md).
- **espn**: injuries endpoint is current-state only -- Wayback backfill is
  the only historical path, and archive.org intermittently 403s a
  snapshot the CDX index says succeeded (403 is in the retryable set just
  for this client). `gameInfo.officials` can be entirely absent -- fail
  open. Transactions are unstructured free text; `transaction_classifier.py`
  is a best-effort heuristic, not a parser, with documented limitations.
- **kalshi**: prices are dollar-strings (`yes_bid_dollars`), not legacy
  integer cents, across all three parsers (`parser.py`, `trade_parser.py`,
  `candle_parser.py`) -- reading the wrong field silently yields an
  all-null column. Market title format changed 2026-07-13→07-27
  (`game_matching.py` keeps **both** old and new regexes permanently,
  since the DB holds rows written under the old shape -- this incident
  dropped the match rate to 0.0% for 18,042 rows before detection).
  Candlesticks can have an entirely absent price block on no-trade bars.
- **odds_api**: auth via query-string `apiKey=` (not a header) -- routed
  through `redact_query_param_keys` so it never leaks into logs/exceptions.
  Costs `[markets] x [regions]` per request, **not** per request (a real
  season overspend happened from this). Event ids get reissued mid-game,
  so are not durable keys. Per-event historical calls 404 for old dates --
  expected, not an error. Player props are metered separately from bulk
  odds.
- **polymarket**: two hosts with different mutability semantics (`?tag=`
  silently doesn't filter on gamma-api, only `tag_slug` works). Trades
  page limit is silently server-clamped above 500, so pin it client-side.
  Trader profile fields are deliberately dropped to keep the fills table
  immutable.
- **wnba_official**: no index/latest alias for the PDF -- probes candidate
  hourly filenames newest-first. PDF text has no delimiters, parsed by
  document-order anchor scanning. Team names must be caller-supplied,
  never regex-guessed (a wrong guess would silently reassign a player to
  the opposing team). Documented real disagreement with ESPN on
  2026-08-17 for the same player.
- **wnba_stats**: requires browser-spoofing headers or the request hangs
  to timeout rather than erroring. `LeagueID=10` must be explicit or it
  silently returns NBA data. 5-team abbreviation crosswalk is hardcoded,
  deliberately not fuzzy-matched.

- **NBA (multi-league, NBA_EXPANSION.md)**: `espn`, `wnba_stats`, and
  `wnba_official` each take a `league` param. **Never assume a provider's
  external ids are globally unique across leagues without a live test.**
  ESPN's own site API reuses small per-sport integers -- WNBA's Minnesota
  Lynx and NBA's Detroit Pistons both carry ESPN team id `"8"`, confirmed
  live 2026-08-22. `espn`'s `provider_entity_map` string is therefore
  league-scoped too (`"espn"` / `"espn_nba"`), same pattern as
  `wnba_stats`/`nba_stats`. A first pass that shared one `"espn"` string
  silently merged an NBA team onto an existing WNBA crosswalk row and
  overwrote its name -- caught by `tests/integration/
  test_nba_league_scoping_e2e.py`, not by inspection.

Also see `AGENTS.md`'s "Providers are inconsistent in specific, documented
ways" and "Vendor archive boundaries" sections -- bovada's reversed
"Last First" player names, `player_aliases.py` for curated name drift, and
the-odds-api's featured-markets-start-May-2022 / player-props-start-May-2023
boundaries.

## Naming and layering conventions

- Matching helpers are consistently named `game_matching.py` /
  `player_prop_matching.py` / `team_market_matching.py` across `kalshi`
  and `polymarket`.
- Pipeline files are `<provider>_<subject>_ingest.py`, one per ingest
  path (some providers have several, e.g. `balldontlie` has 9).
- Every `client.py` instantiates the shared `wnba_engine/http_client.py`
  `JsonHttpClient` with provider-specific base URL/headers/pacing.
  `wnba_engine/parsing.py` supplies shared `require`/`optional`/`parse_*`
  helpers; `wnba_engine/errors.py`'s `ProviderValidationError` is raised
  by every parser.
- Parsers never import `repositories` or open a DB connection -- only
  `pipeline/*_ingest.py` does resolution (via `entity_repo.py`) and
  persistence (via `repositories/*_repo.py`).

## Adding a new provider

Onboarding never means a new table -- external ids resolve through the
existing `provider_entity_map` crosswalk. Follow the client/parser/
matching split above, add a `pipeline/<provider>_*_ingest.py`, a CLI
subcommand in `wnba_engine/cli/main.py`, and if it's recurring, a job in
`deploy/schedule.toml` (see [[runtime-services]]). Update this skill's
table when you do.

If a provider serves more than one league (as `espn`/`wnba_stats`/
`wnba_official` now do), verify live whether its external ids are actually
unique across leagues before reusing one `provider_entity_map` string for
both -- do not trust "this API looks globally namespaced" without testing
it (see the NBA gotcha above). If they collide, give each league its own
provider string exactly like `wnba_stats`/`nba_stats` and `espn`/
`espn_nba` do.
