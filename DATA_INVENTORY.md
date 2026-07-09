# Data Inventory

What's actually in this database, where each piece comes from, and how to
get more of it. Row counts below are a snapshot (see "How to refresh this
doc") — several pipelines run on a recurring schedule and grow these
numbers continuously; treat the counts as "order of magnitude as of last
update," not a live figure.

See `ROADMAP.md` for the why (breadth-as-moat, one adapter per provider,
canonical crosswalk). This doc is the what.

## Table of contents
- [Sources at a glance](#sources-at-a-glance)
- [ESPN](#espn-free-public-site-api)
- [balldontlie.io](#balldontlieio-paid-goat-tier)
- [Kalshi](#kalshi-regulated-prediction-market)
- [Polymarket](#polymarket-prediction-market)
- [Known but NOT integrated](#known-but-not-integrated)
- [Canonical schema & crosswalk](#canonical-schema--crosswalk)
- [Data quality / validation](#data-quality--validation)
- [Recurring ingestion schedule](#recurring-ingestion-schedule)
- [CLI command reference](#cli-command-reference)
- [How to refresh this doc](#how-to-refresh-this-doc)

---

## Sources at a glance

| Source | Cost | What it gives us | Cadence |
|---|---|---|---|
| ESPN | Free (public site API) | Scores, box scores, live + historical injuries | Daily sync + 2h injury snapshot |
| balldontlie.io | Paid (GOAT tier) | Advanced stats, play-by-play, shot zones, bio, standings, sportsbook odds, second box-score/injury source | Weekly + 2h for time-sensitive parts |
| Kalshi | Free (public API) | Regulated prediction-market prices (games, spreads/totals, player props) | 2h snapshot |
| Polymarket | Free (public API) | Prediction-market prices (games, spreads/totals, player props) | 2h snapshot |
| the-odds-api | N/A | **Not integrated** — see below | — |

---

## ESPN (free, public site API)

The sole source of **final scores** and the original box-score provider.
No API key required (`site.api.espn.com`).

- **`games`** — one row per game, 2022–present. `season_type` distinguishes
  preseason / regular-season / post-season / other (the last catches things
  like the All-Star Game, which ESPN itself flags `season.type=2` but which
  a separate `competitions[].type.abbreviation == "ALLSTAR"` field lets us
  correctly exclude from real standings — see the games/teams fix in git
  history if you need the details).
- **`teams`** — canonical team identity. `is_franchise` flags the 15 real
  WNBA teams vs. 11 non-franchise entities (national teams like Brazil/Japan
  that show up in preseason exhibitions, and All-Star-roster constructs
  like "Team Wilson").
- **`team_game_stats`, `player_game_stats`** (`source = 'espn'`) — full box
  scores: shooting splits, rebounds (off/def), assists, steals, blocks,
  turnovers, fouls, plus/minus, starter/DNP flags.
- **`injury_reports`** (`source = 'espn'`) — live, current-state-only
  league injury report. No historical version exists via this endpoint.
- **`injury_reports`** (`source = 'espn-wayback'`) — the real historical
  injury feed: ESPN's live injuries page has no history endpoint, so this
  is scraped from the Wayback Machine's daily archive of that same page,
  back to 2022-04. ~100% of what's recoverable from the archive has been
  captured; the only gaps are days archive.org itself never crawled.
- **`game_plays`, `player_advanced_stats`, etc. also cross-reference ESPN
  IDs** via the crosswalk, but the actual rows for those come from
  balldontlie — see below.

CLI: `sync-espn --date`, `backfill-espn --since/--until`, `sync-recent`,
`snapshot-injuries`, `backfill-injuries-wayback --since/--until`.

---

## balldontlie.io (paid, GOAT tier)

Everything below requires `WNBA_ENGINE_BALLDONTLIE_API_KEY` (`.env`,
gitignored). balldontlie's own game/player/team IDs are a different ID
space from ESPN's — resolved to our canonical IDs via
`wnba_engine/pipeline/balldontlie_game_resolution.py` (team+date matching)
and `entity_repo.resolve_or_create_player_by_name` (name-match fallback),
never by inventing a second parallel identity.

- **`player_advanced_stats`, `team_advanced_stats`** — offensive/defensive
  rating, pace, true shooting %, effective FG%, usage%, assist%, rebound%,
  PIE, and the "four factors," per player-game and team-game. No free
  source provides this reliably (ESPN doesn't have it; stats.wnba.com is
  real but fights bot detection too aggressively — see below).
- **`team_game_stats`, `player_game_stats`** (`source = 'balldontlie'`) —
  a SECOND, independent box-score source for the same games ESPN already
  covers, same columns, different `source` value. Exists for cross-source
  validation, not because ESPN's numbers were wrong — the validation suite
  checks these agree.
- **`game_plays`** — full play-by-play: 400+ events per game (type,
  free-text description, team, running score, period/clock, scoring
  flag). No structured player ID on individual plays — player names live
  in the free-text description only; extracting them is left to a future
  consumer, not guessed at ingestion.
- **`player_shot_zone_stats`, `team_shot_zone_stats`** — season-level FGA/
  FGM broken into 8 court zones (restricted area, mid-range, corner 3s,
  above-the-break 3, backcourt). Despite balldontlie's endpoint name
  ("shot_locations"), this is **not** per-shot x/y coordinate data —
  balldontlie doesn't expose spatial shot charts, only zone aggregates.
- **`players.height/weight/jersey_number/college/age`** — biographical
  data riding along on every advanced-stats/shot-zone/players-endpoint
  response. `age`/`jersey_number` are mutable snapshot values, refreshed
  on every re-ingestion; `height`/`weight`/`college` are effectively
  permanent.
- **`team_standings`** — official current-state standings (upsert on
  team+season): wins, losses, win%, games behind, home/away/conference
  record, playoff seed. Authoritative, not something we'd want to compute
  ourselves and risk getting tiebreakers wrong.
- **`team_standings_history`** — the append-only companion to the above:
  a timestamped snapshot on every ingestion run, for "how did the standings
  trend over the season" rather than only "what are they right now."
- **`sportsbook_game_odds`, `sportsbook_player_prop_odds`** — real
  bookmaker lines (moneyline/spread/total, player-prop over-under),
  structurally distinct from Kalshi/Polymarket's prediction-market
  contracts (bookmaker vig vs. peer-to-peer contract pricing — genuinely
  different market structure, not redundant). Game-level odds
  (`/wnba/v1/odds`) only exposes a **rolling recent window**, not full
  history — confirmed live, hence the 2-hourly capture cadence (see
  schedule below); missing a window is lost history, same property as the
  ESPN injury feed.
- **`balldontlie_injury_reports`** — a second live injury source. Kept
  separate from `injury_reports` rather than merged in: balldontlie's
  shape is genuinely thinner (single free-text `status`, no
  injury_type/side fields, `return_date` is a bare "Mon D" string with no
  year) — forcing it into ESPN's structured columns would mean inventing
  values, not real data.

CLI: `backfill-advanced-stats --season`, `backfill-team-advanced-stats
--season`, `backfill-balldontlie-stats --season` (traditional box scores),
`backfill-plays --season`, `backfill-shot-zones --season`,
`backfill-players` (full `/players` sweep, not tied to a season),
`backfill-standings --season`, `backfill-odds --since/--until`,
`backfill-player-prop-odds --season`, `snapshot-balldontlie-injuries`.

### stats.wnba.com — investigated, not viable

Real (TLS cert issued to NBA Media Ventures, LLC), reachable with the exact
header set actively-maintained open-source clients (`nba_api`, `wehoop`)
use — but Akamai bot protection silently black-holes the connection after
~8 requests regardless of correct headers. Not viable for a reliable
pipeline; balldontlie already does this work reliably behind a normal API
key, which is why it's the paid source of record instead.

---

## Kalshi (regulated prediction market, free public API)

`market_price_snapshots` (`provider = 'kalshi'`). Prices normalized to
implied probability `[0, 1]` at parse time regardless of Kalshi's
dollar-string quoting.

- **Game winner markets** (`KXWNBAGAME`) — resolved to canonical `game_id`
  via ticker date + team names.
- **Team-level derivatives** — full-game and quarter/half spreads and
  totals, quarter/half/OT winners (`KXWNBASPREAD`, `KXWNBATOTAL`,
  `KXWNBA1QSPREAD` .. `KXWNBA4QWINNER`, `KXWNBAOT`, ...). Two different
  title shapes depending on series (two-team "X vs Y" vs. single-team "X
  wins by over N points?") — see `wnba_engine/kalshi/team_market_matching.py`.
- **Player-prop markets** (`KXWNBAPTS/REB/AST/3PT`) — "{Player}: N+
  {stat}" titles. No team name in the title or decodable team code in the
  ticker; resolved via player name → their most recent team → that team's
  game near the prop's date, not via the ticker at all.
- **Season-long futures/awards** (`KXWNBAMVP`, `KXWNBAROY`, `KXWNBAALLTEAM`,
  etc.) — deliberately left unmapped to any `game_id` (there isn't one).
  See "Known but NOT integrated" for the awards-ground-truth gap this
  implies.

CLI: `snapshot-kalshi [--series]`.

---

## Polymarket (prediction market, free public API)

`market_price_snapshots` (`provider = 'polymarket'`).

- **Team matchup markets** ("TeamA vs. TeamB") and **derivative markets**
  ("Spread: {Team} (-N)", "{TeamA} vs. {TeamB}: O/U {N}") — resolved via
  team name + `close_time` proximity.
- **Player-prop markets** ("{Player}: {Stat} O/U {Line}") — same
  player-name → recent-team → nearby-game resolution as Kalshi's props.
- **Season-long futures** — same as Kalshi, deliberately unmapped.

CLI: `snapshot-polymarket`.

---

## Known but NOT integrated

- **the-odds-api.com (Phase 0)** — a separate, private, personal
  data-hoarding pipeline that predates and inspired this repo (see
  `ROADMAP.md`). Real data that already exists: **four seasons of WNBA
  historical odds (2022–present) across 32 sportsbooks**, with
  line-movement snapshots (T-7d / T-24h / T-1h / closing, not just a single
  closing price), plus final scores for ~100% of completed games. Per
  `db/migrations/0001_canonical_entities.sql`'s precedence comment, this
  source is intended to outrank ESPN for final scores once folded in.
  **Not currently joined to anything in this database** — folding it in is
  a deliberate later decision, not a blocker.
- **Referee/officiating data** — investigated; not present in ESPN's or
  balldontlie's WNBA payloads. Not built.
- **Transactions/roster moves** — investigated; no clean structured source
  found in either provider as of this writing.
- **Season awards ground truth** (actual MVP/ROY/DPOY/All-WNBA/etc.
  winners) — the thing that would let the season-long Kalshi/Polymarket
  award markets actually be backtested. Real historical fact, not
  API-driven — needs manual research/curation. Status: in progress as of
  this doc's last update, check `git log` for whether it landed.
- **Venue/attendance data** — status: in progress as of this doc's last
  update, check `git log`.

---

## Canonical schema & crosswalk

- **`teams`, `players`, `games`** — our own ID space, not shaped after any
  single provider. Every provider's external IDs resolve to these through
  `provider_entity_map`.
- **`provider_entity_map`** — `(provider, entity_type, external_id) ->
  internal_id`. One table for every provider and entity type (ESPN
  team/player/game IDs, balldontlie's own numeric IDs, Kalshi event
  tickers, Polymarket event IDs, ...), so onboarding a new source never
  means a new table.
- Score precedence: ESPN is currently the sole score source. the-odds-api
  (not yet integrated — see above) is documented to outrank it once it is.

---

## Data quality / validation

`wnba_engine/validation/` — 11 checks, run via `wnba-engine validate`
(exits non-zero on any failure):

1. `orphaned_crosswalk_entries` — every `provider_entity_map.internal_id`
   references a real row (no FK possible; it's polymorphic).
2. `duplicate_crosswalk_mappings` — one provider's external_id never maps
   many:1 onto a canonical row (catches bad name-match merges).
3. `team_box_score_matches_final_score` — SUM(player points) vs.
   `games.home_score/away_score`, two different ESPN endpoints.
4. `team_totals_match_player_sums` — team box score totals vs. SUM of
   that team's player rows.
5. `plays_final_score_matches_game_score` — balldontlie's play-by-play
   final score vs. ESPN's scoreboard. Anchored on the `"End Game"` play
   type, not `MAX(sequence)` — balldontlie's own `order` field isn't
   reliably monotonic (verified live: a period-1 jumpball can carry a
   spuriously high sequence number). As of last check: 6 genuine 1-2
   point disagreements out of 1,239 games (0.48%) — real upstream noise
   between two independent providers, not a bug.
6. `team_stat_bounds`, `player_stat_bounds` — no makes-exceed-attempts,
   `oreb + dreb == rebounds`.
7. `market_price_bounds` — probabilities/bid/ask stay in `[0, 1]`.
8. `player_shot_zone_bounds`, `team_shot_zone_bounds` — no zone with
   `fgm > fga`.
9. `non_franchise_team_in_regular_season` — no `regular-season` game
   involves a team that isn't a real recognized franchise (the All-Star
   Game bug class — see ESPN section above).

---

## Recurring ingestion schedule

Managed via macOS LaunchAgents, source of truth in `~/dotfiles/mac/`
(`LaunchAgents/*.plist` + `wnba-analytics-engine/*.sh`), mirrored from this
repo's CLI commands. All scripts no-op if the project/Postgres/`.env` isn't
present on that machine.

| Job | Cadence | What |
|---|---|---|
| `espn-sync.sh` | Daily | Trailing-window ESPN re-sync (catches scheduled→final transitions) |
| `market-and-injury-snapshot.sh` | Every 2h | Kalshi + Polymarket snapshots, ESPN injuries, balldontlie standings + odds (both are rolling-window/frequently-changing — a missed capture is lost, not just stale) |
| `balldontlie-season-sync.sh` | Weekly | Advanced stats, team advanced stats, plays, shot zones, player-prop odds, for the current season |

Historical backfills (`--season 2022` etc.) are run manually/by agent, not
on a recurring schedule — the recurring jobs only cover the current season
plus rolling-window data.

---

## CLI command reference

Run via `uv run wnba-engine <command>` from the repo root.

| Command | Source | Notes |
|---|---|---|
| `migrate` | — | Apply pending SQL migrations |
| `sync-espn --date` | ESPN | One date's scoreboard + box scores |
| `backfill-espn --since --until` | ESPN | Date range |
| `sync-recent [--days]` | ESPN | Trailing window (for cron) |
| `snapshot-kalshi [--series]` | Kalshi | Current market prices |
| `snapshot-polymarket` | Polymarket | Current market prices |
| `snapshot-injuries` | ESPN | Current league injury report |
| `snapshot-balldontlie-injuries` | balldontlie | Current league injury report (2nd source) |
| `backfill-injuries-wayback --since --until` | ESPN via Wayback | Historical injury status |
| `backfill-advanced-stats --season` | balldontlie | Player advanced stats |
| `backfill-team-advanced-stats --season` | balldontlie | Team advanced stats |
| `backfill-balldontlie-stats --season` | balldontlie | Traditional box scores (2nd source) |
| `backfill-plays --season` | balldontlie | Play-by-play |
| `backfill-shot-zones --season` | balldontlie | Shot-zone efficiency splits |
| `backfill-players` | balldontlie | Full `/players` sweep (not season-scoped) |
| `backfill-standings --season` | balldontlie | Official standings (current + history) |
| `backfill-odds --since --until` | balldontlie | Game-level sportsbook odds |
| `backfill-player-prop-odds --season` | balldontlie | Player-prop sportsbook odds |
| `validate` | — | Run all data-quality checks |

---

## How to refresh this doc

Row counts and table lists above are a point-in-time snapshot. To get the
current real numbers:

```bash
# Table list
docker exec -i wnba-analytics-engine-postgres-1 psql -U wnba -d wnba_engine -c "\dt"

# Row counts for every table this doc references
docker exec -i wnba-analytics-engine-postgres-1 psql -U wnba -d wnba_engine -c "
select 'games', count(*) from games
union all select 'teams', count(*) from teams
union all select 'players', count(*) from players
union all select 'team_game_stats', count(*) from team_game_stats
union all select 'player_game_stats', count(*) from player_game_stats
union all select 'game_plays', count(*) from game_plays
union all select 'player_advanced_stats', count(*) from player_advanced_stats
union all select 'team_advanced_stats', count(*) from team_advanced_stats
union all select 'player_shot_zone_stats', count(*) from player_shot_zone_stats
union all select 'team_shot_zone_stats', count(*) from team_shot_zone_stats
union all select 'team_standings', count(*) from team_standings
union all select 'team_standings_history', count(*) from team_standings_history
union all select 'injury_reports', count(*) from injury_reports
union all select 'balldontlie_injury_reports', count(*) from balldontlie_injury_reports
union all select 'market_price_snapshots', count(*) from market_price_snapshots
union all select 'sportsbook_game_odds', count(*) from sportsbook_game_odds
union all select 'sportsbook_player_prop_odds', count(*) from sportsbook_player_prop_odds;
"

# Full migration history (source of truth for schema)
ls db/migrations/

# Full CLI command list (source of truth for what's ingestible)
grep -n '@cli.command' wnba_engine/cli/main.py

# Data quality status
uv run wnba-engine validate
```
