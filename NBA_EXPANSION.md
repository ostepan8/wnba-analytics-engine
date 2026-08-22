# NBA expansion — research, plan, and implementation status

Researched 2026-08-22. WNBA and NBA seasons are close to back-to-back
(confirmed below), so adding the NBA closes the WNBA off-season dead zone
almost completely.

**Implementation status as of 2026-08-22 (same day, follow-up session):**
Option A (the `league` column approach recommended below) was implemented
and proven against real live data -- this is no longer just a plan. See
`## Implementation status` near the end of this doc for exactly what
landed, what's still open, and a real bug this pass caught and fixed (a
cross-league ESPN team-id collision that a shared `provider="espn"`
crosswalk string would have silently merged). The research below is left
intact as-written since it's still the accurate record of what was
verified and how; only the status section at the end is new.

**A tooling constraint on this research pass, stated up front so nothing
below is over-trusted:** this session had no working shell (`Bash` was
unavailable throughout) and no access to `.env`, so nothing requiring an
API key (balldontlie, the-odds-api) or custom headers (stats.nba.com) could
be tested with a real authenticated request. Everything marked **live** below
really was fetched live, unauthenticated, this session. Everything marked
**docs** is from the provider's public documentation, not a live call.
Everything marked **code** is inferred from this repo's existing,
already-verified-live WNBA client code and its own doc comments. Two hosts
(ESPN's site API, the NBA CDN that serves both leagues' injury PDFs) could
not be reached at all from this sandbox -- not a 403 tied to the NBA path
specifically, but a full timeout/block on **the exact same WNBA URLs this
repo's production code already hits successfully**, proven by testing the
known-good WNBA URL as a control and getting the identical failure. That's
a WebFetch-tool limitation in this session, not a real signal about NBA
reachability -- treat those two rows as high-confidence-by-pattern, not
verified, and confirm with a real HTTP client (trivial -- the existing
`wnba_official/client.py` and `espn/client.py` already have every header/auth
detail they'd need) before relying on them.

## Per-provider coverage

| Provider | NBA equivalent exists? | Free? | Tested this session | Notes |
|---|---|---|---|---|
| `wnba_stats` (stats.wnba.com / stats.nba.com) | **Yes** | **Yes** | **code** (not live-tested, but see below) | Already documented in this repo's own `wnba_engine/wnba_stats/client.py` docstring: *"`LeagueID=10` is the WNBA... 00 is the NBA and 20 the G-League."* This is the highest-confidence finding in this whole doc -- it's not an inference, it's an existing comment in shipped code. Same host, same auth-free pattern, same browser-header requirement, same client class -- just a different `LeagueID` value. |
| `kalshi` | **Yes** | **Yes** | **live** | `KXNBAGAME` series confirmed live: `GET /trade-api/v2/series/KXNBAGAME` returns 200, title "Pro Basketball Game", category "Sports". `GET /markets?series_ticker=KXNBAGAME` returned 5 real open markets for games Oct 20-21, 2026 (San Antonio @ OKC, Philadelphia @ New York, Boston @ Detroit). No auth needed, same as WNBA. The broad `/series?category=Sports` listing this repo's matching code might assume is easy to enumerate NBA series from is **not reliable** -- a plain substring search on that endpoint's response surfaced only prop/prepack series (`KXNBAPREPACK3ML`, `KXNBACELEBRITYGAME`, `KXNBA2D`, `KXNBADRAFT5`) and missed `KXNBAGAME` entirely, almost certainly because the category is large and got truncated by this session's tooling -- don't trust an automated "list all NBA series" pass without pagination; the game-winner ticker had to be found by guessing the exact `KXWNBAGAME` → `KXNBAGAME` naming-convention swap and querying it directly. |
| `polymarket` | **Yes** | **Yes** | **live** | `GET /events?tag_slug=nba&closed=false` returned real, valid, non-empty data: LeBron James retirement market, Steph Curry trade market, and a 30+-team NBA 2027 Championship futures market. Same `tag_slug` parameter, same host, same "closed=false" convention as the existing `wnba_engine/polymarket/client.py`. Per-game markets aren't visible yet in this data (NBA season hasn't started -- see calendar below) but the tag/host pattern is proven live. |
| `odds_api` (the-odds-api) | **Yes** | **No -- but already paid for** | **docs** | Public docs confirm the sport key is `basketball_nba` (parallel to `basketball_wnba`), and player props are supported the same way (per-event odds endpoint, `markets=player_points,...` shown in their docs). This account already has no free tier for either league, so this isn't a *new* cost -- but see the credit-budget warning below, it's a real constraint on *when* to turn this on. |
| `wnba_official` (NBA CDN injury PDF) | **Very likely, same pattern** | **Yes** | **not reachable this session** (see tooling-constraint note above; the exact WNBA URL failed identically as a control) | This repo's own `wnba_engine/wnba_official/client.py` docstring already documents the URL as `.../referee/wnba_injury/Injury-Report_<date>_<time>.pdf` on `ak-static.cms.nba.com` -- the same CDN that serves the NBA's own report. `.../referee/nba_injury/...` is the obvious candidate given every other provider in this table confirmed the identical `wnba`→`nba` path-segment swap. Confirm with a real HTTP client, not WebFetch (this session's tool couldn't reach the CDN at all, WNBA or NBA). |
| `espn` | **Very likely, same pattern** | **Yes** | **not reachable this session** (same tooling limitation, WNBA control URL failed identically) | `wnba_engine/config.py`'s `DEFAULT_ESPN_BASE_URL` is `.../sports/basketball/wnba`; ESPN's site API is famously uniform across every sport it covers (nfl/nba/wnba/mlb/nhl/ncaaf/ncaab all follow this exact pattern) -- `.../sports/basketball/nba` is the obvious candidate. Same caveat as above: confirm with a real client (`httpx.get`, no special headers needed per the existing `EspnClient`), not WebFetch. |
| `balldontlie` | **Yes, but NOT covered by the existing subscription** | **No** | **docs** | This is the one real "not free" finding, and it's worth being direct about: balldontlie's own public docs state *"Paid tiers do not apply across sports. The tier you purchase for NBA will not automatically be applied to other sports,"* and NBA's advanced-stats/standings/odds/injuries endpoints require their own GOAT tier (**$39.99/mo**, a second subscription on top of the one already paying for WNBA). NBA's URL structure is also different from what the WNBA-path-swap pattern would predict -- it's `/v1/games`, `/v1/stats`, `/v1/stats/advanced`, `/v1/standings`, `/v2/odds`, `/v1/player_injuries` (no `/nba/` prefix at all; NBA is balldontlie's original/default sport family). **Per your instruction not to be forced into paying: don't add balldontlie for NBA.** It isn't needed anyway -- see the free alternative below. |

### The free alternative to paying balldontlie again

Everything balldontlie's NBA tier would provide -- advanced stats (offensive/
defensive rating, four factors, PIE), traditional box scores, standings,
play-by-play, shot locations -- has a free NBA-side equivalent already proven
to exist for this exact repo's provider family: **stats.nba.com** (`LeagueID=00`,
same host, same client class as `wnba_stats`) publishes the NBA's own advanced
box-score/four-factors endpoints (`leaguedashplayerstats` and siblings) the
same way it publishes `leaguegamelog`/`playbyplayv2`/`shotchartdetail`, which
this repo already consumes for the WNBA. balldontlie was originally brought in
for the WNBA specifically because *ESPN lacks advanced stats and stats.wnba.com
fights bot detection* (per this repo's `wnba_stats` provider notes in the
`data-providers` skill) -- but stats.nba.com's bot-gating is the SAME
mechanism this repo already has a working, documented answer for (the
browser-spoofing headers in `wnba_engine/wnba_stats/client.py`), so the
reason balldontlie exists for WNBA doesn't apply the same way for NBA. ESPN
alone (box scores, traditional stats, schedule) plus an expanded
`wnba_stats`/`nba_stats` client (advanced stats, shot locations, PBP) covers
the same ground for $0/mo.

## Season calendar (confirmed, not assumed)

- **WNBA 2026**: this project's own database has games scheduled through
  `2026-09-25` (confirmed via `wnba-cli --compact markets summary`'s
  `latest_game` field this session).
- **NBA 2026-27**: confirmed live via the Kalshi `KXNBAGAME` markets pulled
  this session -- real scheduled games starting **2026-10-20**.

That's roughly a **3-4 week gap**, not the months-long dead zone the
"complementary seasons" framing might suggest at first glance -- the two
leagues are nearly back-to-back. NBA's regular season/playoffs then run into
mid-June (public knowledge, not independently re-verified this session),
covering the WNBA's own off-season almost completely. The year-round-coverage
case holds up on real dates, not just the general shape of two leagues having
different windows.

## Architecture recommendation: how to handle two leagues in one schema

This is the one part of this doc that's a genuine judgment call, not a fact
to verify -- **treat this section as a recommendation for review, not
something already decided.**

**The core tension:** this project's canonical-identity design
(`provider_entity_map(provider, entity_type, external_id) -> internal_id`,
plus best-effort name/abbreviation matching in `entity_repo.py`) was built
assuming one league. Nothing in the current schema stops "Washington" or
"GS" from meaning different real-world teams depending on which league a row
came from, because there was only ever one league to disambiguate.
`find_team_by_abbreviation`/`find_team_by_name` and every ticker-parsing
matcher (`kalshi/game_matching.py`, `polymarket/game_matching.py`, etc.) are
deliberately non-fuzzy and exact-match by design (per this project's own
"never by fuzzy matching" convention) -- but exact-match still collides if
two leagues share a short code, and nothing currently scopes the match to
one league.

**Option A -- add a `league` column, scope uniqueness and matching by it
(recommended).** Add `league text not null` (`'wnba'` / `'nba'`, a check
constraint not an enum type, consistent with this project's plain-SQL
style) to `teams`, `games`, and `players` (players too, not just derived
from their team -- name-matching ambiguity across leagues is a
same-Tuesday risk even though roster overlap isn't). Every place that
currently assumes single-league uniqueness (team abbreviation lookups,
`provider_entity_map`'s implicit safety, standings, season aggregates)
gets `AND league = %(league)s` added to its query, and every matching
helper takes an explicit `league` parameter the same way `find_player_by_name`
already takes an explicit `allow_reversed` parameter for a different
disambiguation problem. This is additive, keeps the "one queryable
dataset" value proposition that's literally this project's stated purpose
(AGENTS.md: "...joined into one queryable dataset"), and every existing
WNBA row gets `league='wnba'` in one backfill UPDATE with no other schema
change. `provider_entity_map` may or may not need `league` added to its
own uniqueness key depending on whether external ids are already globally
unique per provider (ESPN's and Kalshi's look like they are, from what
this session confirmed; balldontlie's are unconfirmed and moot since
balldontlie isn't planned for NBA per the recommendation above).

**Option B -- fully separate schema/database per league.** Maximally
safe against cross-league collision, but throws away the entire value of
this project as currently designed -- every repository function, every
API route, every feature-layer query would need a duplicate or a league
parameter threaded through it anyway (so it doesn't actually avoid Option
A's work), the frontend would need two of everything, and cross-league
analytics (e.g. comparing divergence-detection performance across both
leagues, which is a real reason to want both in one place) becomes a
cross-database join instead of a `WHERE` clause. Not recommended.

**Recommendation: Option A.** It's the smaller, more reversible change,
and it's the one that doesn't quietly abandon what this project is
actually for.

## Phased implementation plan (once the schema approach is approved)

Rough effort, not a commitment -- for scoping only.

1. **Schema**: one migration adding `league` to `teams`/`games`/`players`
   with a default backfill to `'wnba'`, plus whatever `provider_entity_map`
   change Option A turns out to need. ~1 migration file, ~1 day including
   the validation-check updates this will require (every check in
   `wnba_engine/validation/` that assumes one league needs a second look).
2. **NBA provider clients**: extend `wnba_stats` to accept `LeagueID` as a
   parameter instead of a hardcoded constant (small, mechanical), add an
   `espn` NBA base URL, add a `wnba_official`→`nba_official` PDF path
   (or generalize the existing client to take a league-scoped path
   segment instead of duplicating the whole module -- prefer the latter,
   matches this project's "many small files, not many similar files"
   convention only where the logic actually differs). ~3-5 files.
3. **Kalshi/Polymarket matchers**: add NBA ticker/title regex patterns
   alongside the existing WNBA ones in `game_matching.py` and siblings --
   confirmed live this session that `KXNBAGAME` and `tag_slug=nba` exist,
   so this is concrete work, not speculative. ~2-4 files, mostly new
   regex cases plus tests built from real captured NBA payloads (this
   project's own convention -- "fixtures are trimmed from real
   live-captured payloads, never hand-written").
4. **Pipeline + repositories**: thread `league` through the
   fetch→parse→resolve→persist path and every repository query that's
   currently single-league-implicit. This is the largest, most
   diffuse piece of work -- budget the most time here, not in step 2.
5. **the-odds-api NBA**: last, deliberately, and gated on a real look at
   remaining credit budget first -- **do not enable `basketball_nba` odds
   calls on the current key without checking `x-requests-remaining`
   first.** The existing WNBA budget is already the tightest constraint in
   this whole project (~500 credits, `odds-focused` already disabled for
   it per `deploy/schedule.toml`), and this account's quota is very
   likely one pool shared across every sport on the key, not a separate
   allowance per sport -- confirm this from the account dashboard/invoice
   before assuming otherwise, and treat "the NBA odds feed competes with
   the WNBA odds feed for the same scarce credits" as the default
   assumption until proven wrong.
6. **Frontend/API**: a league selector/filter, once the data actually
   exists to filter. Last on purpose -- nothing to show until steps 1-4
   land.

## What's genuinely not free, stated plainly

Only one thing in this whole investigation: **balldontlie's NBA tier**,
$39.99/mo, a separate subscription from the one already covering WNBA. The
recommendation above is to skip it entirely and cover the same ground with
ESPN + an expanded `wnba_stats`-style NBA client, both free. Everything
else in this doc -- stats.nba.com, Kalshi, Polymarket, ESPN, the NBA CDN
injury PDF, and the-odds-api's NBA sport key on the account already paying
for WNBA -- is free or already paid for.

## Implementation status (2026-08-22, worktree `nba-expansion`)

Option A landed. Verified against a real (throwaway, local) Postgres
instance running this repo's actual migrations, and against real live data
pulled from ESPN's NBA site API and Kalshi's `KXNBAGAME` series -- not just
unit-tested in isolation.

**Done and proven live:**

- **Schema**: `db/migrations/0038_league_column.sql` adds `league TEXT NOT
  NULL DEFAULT 'wnba' CHECK (league IN ('wnba','nba'))` to `teams`,
  `players`, `games`, plus `games_league_season_idx` replacing the old
  single-column season index. `provider_entity_map` was deliberately left
  alone -- see the collision finding below for why that almost went wrong.
- **`wnba_engine/repositories/entity_repo.py`**: every team/player/game
  lookup that assumed single-league uniqueness now takes an explicit
  `league` parameter (default `"wnba"`, so no existing caller changes
  behavior): `find_team_by_abbreviation`, `find_team_by_name`,
  `find_team_by_name_fragment`, `find_player_by_name`,
  `find_game_id_by_teams`, `list_games_in_range`, `list_team_names`,
  `resolve_or_create_player_by_name`. `resolve_or_create_team`/
  `resolve_or_create_player`/`upsert_game` write `league` from the
  `TeamRef`/`PlayerRef`/`ScoreboardGame` DTOs (`wnba_engine/models/`),
  which now carry a `league: str = "wnba"` field each.
- **ESPN** (`wnba_engine/espn/`): `EspnClient(settings, league=...)`
  switches base URL (`espn_nba_base_url`, confirmed live identical
  response shape to WNBA) and, critically, its `provider_entity_map`
  string -- `"espn"` for WNBA, `"espn_nba"` for NBA. `parser.py`'s
  `parse_scoreboard`/`parse_summary` thread `league` down into every
  `TeamRef`/`ScoreboardGame`/`PlayerRef` they build.
  `wnba_engine/pipeline/espn_ingest.py`'s `sync_date`/`backfill` take a
  `league` param; the `wnba-engine sync-espn`/`backfill-espn`/
  `sync-recent` CLI commands got a `--league {wnba,nba}` option
  (default `wnba`).
- **stats.wnba.com / stats.nba.com** (`wnba_engine/wnba_stats/`):
  `WnbaStatsClient(settings, league=...)` switches `LeagueID` (00/10),
  base host, Referer/Origin headers, and provider string (`wnba_stats` /
  `nba_stats`). `wnba_engine/pipeline/wnba_stats_ingest.py` threads
  `client.provider`/`client.league` through `_resolve_game`, `_player_id`,
  `_play_rows`, `_shot_rows`. The `wnba-engine ingest-wnba-stats` CLI
  command got `--league {wnba,nba}`. **Not live-tested**: stats.nba.com
  was sandbox-network-blocked in every session that touched this repo so
  far (the exact WNBA host failed identically as a control both times) --
  a real HTTP client outside this sandbox needs to confirm it before
  relying on it.
- **NBA CDN injury report** (`wnba_engine/wnba_official/`):
  `WnbaOfficialClient(league=...)` switches the CDN path segment
  (`wnba_injury` / `nba_injury`). Confirmed live: the NBA path is
  reachable and returns this CDN's real "no such file" response (403,
  verified identical to a deliberately-wrong WNBA filename), which is
  correct since the NBA season hasn't started and no report has been
  filed yet -- the path works, there's just nothing on it. CLI:
  `snapshot-official-injuries --league {wnba,nba}`.
- **Kalshi** (`wnba_engine/kalshi/game_matching.py`): ticker regex now
  matches `KXNBAGAME` alongside `KXWNBAGAME`. Title regex extended for a
  FIFTH shape found live: NBA event titles are bare (`"Oklahoma City vs
  San Antonio"`, no trailing "winner?"/"wins?" clause) -- confirmed via
  `KXNBAGAME-26OCT20OKCSAS`, a real scheduled Oct 20 2026 game.
- **Polymarket** (`wnba_engine/polymarket/game_matching.py`): needed no
  change -- its "X vs Y" matcher was already league-agnostic; league
  discrimination happens via `tag_slug` at the client/fetch layer.
- **Live data actually pulled and stored**: NBA preseason (2026-10-03,
  Toronto vs Miami) and regular-season (2026-10-20, three games including
  the Detroit/Boston collision-test game) schedules were ingested through
  the real CLI into a real Postgres instance, alongside a WNBA date
  (2026-06-15), proving both leagues coexist in one database with correct
  `league` tagging and no cross-league identity bleed.
- **Tests**: `tests/integration/test_nba_league_scoping_e2e.py` (new) and
  an extension to `tests/unit/kalshi/test_kalshi_game_matching.py` cover
  the two real bugs this pass found (see below) as regression tests, using
  fixtures trimmed from real live-captured payloads, not hand-written
  data. Existing `FakeEspnClient` test doubles across
  `tests/integration/test_ingestion_e2e.py` and
  `test_balldontlie_stats_ingest_e2e.py` needed a `.provider = "espn"`
  attribute added. Full suite (`uv run pytest tests/`) passes: 1055 tests.

**A real bug this pass found and fixed, not foreseen by the research
above:** this doc originally assumed "ESPN's ids are unique across the
whole site API, not just within one sport" (the reasoning for reusing one
`provider="espn"` crosswalk string across both leagues). That assumption
was WRONG, and live ingestion caught it immediately: ESPN's WNBA
Minnesota Lynx and NBA Detroit Pistons both carry ESPN team id `"8"` --
ESPN assigns small per-sport integers, not a globally unique id space. A
first implementation pass that shared `provider="espn"` silently matched
the NBA Pistons onto the existing WNBA Lynx crosswalk row and overwrote
its name. Fixed by giving ESPN the same per-league provider-string split
`wnba_stats`/`nba_stats` already had for the analogous reason (see
`wnba_engine/espn/client.py`'s docstring). The lesson generalizes: do not
trust "provider ids look globally unique" for ANY provider without a live
cross-league collision test like the one now in
`test_nba_league_scoping_e2e.py` -- balldontlie and the-odds-api were
never checked this way (moot for balldontlie, since it's not planned for
NBA; a real open question if the-odds-api NBA is ever turned on).

**Deliberately NOT done in this pass (still matches this doc's own
gates):**

- **balldontlie NBA tier**: skipped, per the recommendation above ($39.99/mo
  second subscription; ESPN + stats.nba.com covers the same ground free).
- **the-odds-api NBA (`basketball_nba`)**: not enabled. This doc's own
  Phase 5 gate says not to without checking remaining credit budget first
  (`x-requests-remaining`), and this pass had no way to check that. The
  client code (`wnba_engine/odds_api/client.py`) still hardcodes
  `SPORT_KEY = "basketball_wnba"` -- untouched.
- **Other repositories with single-league-implicit queries**:
  `analytics_repo.py`, `betting_repo.py`, `form_repo.py`,
  `game_detail_repo.py`, `feature_repo.py` (the point-in-time feature
  layer -- deserves its own careful pass, not a mechanical grep-and-patch,
  given how leakage-sensitive it is), `resolution_repo.py`, `style_repo.py`,
  `clv_repo.py`, `divergence_repo.py`. Most of these inherit correct
  scoping for free once a query's root table is filtered by `league`
  (a game's home/away teams and box-score players can't span leagues), but
  a handful of no-WHERE-at-all aggregates (e.g. `analytics_repo.py`'s
  `SELECT count(*) FROM games`) need an explicit `league` filter added.
  Not touched here -- flagged for a follow-up pass.
- **`wnba_engine/validation/franchise_checks.py`**: hardcodes WNBA season
  lengths (`SCHEDULED_GAMES: dict[int, int]`, 36/40/44 games) and its SQL
  has no league filter. An NBA season is 82 games; this cannot be shared
  as-is. Needs its own `NBA_SCHEDULED_GAMES` table (or a
  `dict[tuple[int, str], int]` key) plus `AND league = %(league)s` on its
  two queries. Not touched here.
- **`wnba_engine/pipeline/name_resolution.py`**: only the deterministic
  `find_player_by_name` lookup was made league-aware. The
  similarity/LLM fallback path (`resolution_repo.find_similar_players`,
  cached decisions) is not yet league-scoped -- needs its own review of
  `resolution_repo.py`'s SQL, not a mechanical parameter thread.
- **`wnba_engine/wnba_stats/team_matching.py`**: the WNBA side has 5 of 13
  team abbreviations hand-verified against real stats.wnba.com payloads
  because they disagree with ESPN's abbreviations. The NBA side has ZERO
  such entries -- not guessed, since stats.nba.com was unreachable from
  every sandbox this expansion touched. `--league nba` on
  `ingest-wnba-stats` will silently under-resolve games until someone with
  real network access captures actual stats.nba.com payloads and fills
  this in the same way the WNBA side was built.
- **Frontend/API league selector**: no changes to `frontend/` or
  `wnba_engine/api/`. Per this doc's original phased plan, this is last on
  purpose -- there isn't yet enough NBA data flowing through the pipeline
  to justify a UI for it.
- **Production deploy**: none of this shipped to `wnba.onephos.com`. It
  was proven against a throwaway local Postgres instance in this worktree,
  not the production database or the docker-compose dev stack.
