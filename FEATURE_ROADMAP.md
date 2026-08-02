# Feature roadmap

Features this engine should support, what each needs, and what makes each
one dangerous. Written to be worked through incrementally -- every entry
names its source table and its leakage hazard, because those are the two
things that decide whether a feature is buildable and whether it is
honest.

Read `AGENTS.md` first for conventions, and `wnba_engine/features/README.md`
for the step/pipeline contract. `MODELING_FINDINGS.md` records what has
already been tried against the market and what it returned -- notably that
this market is efficient, so these features are for **description,
insight, and Phase 2 rules-based work**, not for an assumed betting edge.

## Status

| Strategy | Steps | Columns |
|---|---:|---:|
| `situational_baseline` | 8 | 33 |
| `team_form` | 18 | 61 |
| `team_style` | 13 | 80 |
| `player_form` | 9 | 34 |

## The two rules

1. **Point-in-time or it does not ship.** Every feature is computed from
   data observable strictly before the row's own tip-off. The guard
   enforces this, but only for what a step DECLARES -- see
   `features/guard.py`.
2. **Season aggregates are the default hazard.** Anything phrased as
   "this season's X" contains the game being predicted. Use trailing
   windows or explicit season-to-date accumulators that exclude the
   current row.

Known-unsafe sources, refused by name in `feature_repo`: `team_standings`
(current-state upsert), `season_awards` (end-of-season truth),
`players.age` / `players.jersey_number` (mutable).

---

## 1. Schedule and situation

Cheap, well-understood, mostly built.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| home / away | `games` | done | none |
| rest days | `games` | done | none |
| back-to-back (<36h) | `games` | done | UTC dates mislabel evening games -- measure the gap, not the date |
| games in last 7 / 10 days | `games` | **todo** | none |
| travel: consecutive road games | `games` | **todo** | none |
| days into season | `games` | **todo** | none |
| rest ADVANTAGE vs opponent | `games` | **todo** | needs opponent mirror |
| time-zone crossings | `games.venue_name` | **todo** | venue -> timezone mapping does not exist yet |

## 2. Team form, multi-window

Currently one window (5 games) and one statistic (mean). This is the
thinnest area relative to its value.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| rolling mean, 5 | `team_game_stats` | done | none |
| rolling mean, 10 / 20 / season-to-date | same | **todo** | none |
| exponentially weighted form | same | **todo** | none |
| rolling **variance** (consistency) | same | **todo** | none |
| form **trend** (slope over window) | same | **todo** | none |
| home-only / road-only splits | same | **todo** | thin samples early in a season -- emit a window-count column |
| win / loss streak length | `games` | **todo** | none |
| margin distribution (blowout rate) | `games` | **todo** | none |

## 3. Opponent and matchup

The frame carried `opponent_team_id` and derived nothing from it until
recently. `OpponentFormStep.mirroring()` now mirrors any windowed step.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| opponent rolling form / pace | mirror | done | mirrors pair with their source step |
| opponent season-to-date | mirror | done | same |
| head-to-head history this season | `games` | **todo** | must exclude the current game |
| head-to-head, multi-season | `games` | **todo** | same |
| opponent defensive strength by position | `player_game_stats` | **todo** | needs a position mapping; `players.position` is present |
| pace INTERACTION (both fast / both slow) | mirror | **todo** | none |

## 4. Style and archetype

Two representations exist: season-aggregate vectors for description
(`analysis/style.py`, never a feature) and rolling vectors for prediction
(`steps/style_steps.py`).

| Feature | Source | Status | Hazard |
|---|---|---|---|
| rolling style vector (10 dims) | `team_advanced_stats` | done | none |
| style distance to opponent | derived | done | scale before distance, or it is all pace |
| signed per-dimension gaps | derived | done | keep signed -- direction is information |
| style volatility (5 vs 15 game) | derived | done | none |
| **archetype membership** (grinder / perimeter / rim) | derived | **todo** | cluster centroids must be fit on PRIOR seasons only |
| archetype matchup history | derived | **todo** | confounded with quality -- control for net rating |
| style **trajectory** (velocity + direction) | derived | **todo** | none |
| shot-mix gaps (paint / mid / three) | `team_shot_zone_stats` | **todo** | **season-level data** -- only usable as prior-season context |

## 5. Player level

| Feature | Source | Status | Hazard |
|---|---|---|---|
| rolling pts / reb / ast / min | `player_game_stats` | done | none |
| bio (height / weight / college) | `players` | done | `age`, `jersey_number` are mutable -- refused |
| per-36 rates, rolling | `player_game_stats` | **todo** | ratio OF SUMS, never mean of ratios (see MODELING_FINDINGS) |
| usage / TS% / PIE, rolling | `player_advanced_stats` | **todo** | `minutes` is TEXT here, integer in box scores |
| role: minutes share of team | `player_game_stats` | **todo** | none |
| starter rate, rolling | `player_game_stats` | **todo** | none |
| player style vector, rolling | both | **todo** | season version exists; needs a trailing variant |
| player uniqueness vs league | derived | **todo** | population must be prior seasons only |
| **projected minutes** | none yet | **blocked** | needs lineup news -- the single highest-value missing input |

## 6. Roster composition

Entirely unbuilt, and genuinely novel: characterise a team by the
DISTRIBUTION of its players' style vectors rather than by team totals.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| roster centroid in player-style space | derived | **todo** | prior-season vectors only |
| roster dispersion (specialists vs generalists) | derived | **todo** | same |
| roster continuity year over year | `player_game_stats` | **todo** | none |
| minutes-weighted roster style | derived | **todo** | weight by PRIOR minutes, not this game's |
| available-roster style (injuries applied) | + `injury_reports` | **todo** | daily resolution before 2026-07 |

## 7. Injury and availability

| Feature | Source | Status | Hazard |
|---|---|---|---|
| teammates out | `injury_reports` | tested, no signal | daily resolution historically |
| starters out (minutes-weighted) | + `player_game_stats` | **todo** | weight by prior minutes |
| opponent starters out | mirror | **todo** | same |
| days since a player returned | `injury_reports` | **todo** | none |
| team availability index | derived | **todo** | none |

## 8. Market-derived

**Use with care.** Odds are a legitimate feature -- the line is the best
single forecast available -- but a frame containing the line will look
brilliant and teach nothing. Keep market features in a separate strategy
so they can never silently enter a "pure basketball" model.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| consensus line / total, de-vigged | `sportsbook_game_odds` | **todo** | must be pre-tip captures only |
| cross-book dispersion | same | **todo** | none |
| line movement, open -> current | same | **todo** | none |
| implied win probability | same | **todo** | de-vig first |
| prop line vs rolling mean | `sportsbook_player_prop_odds` | **todo** | none |
| prediction-market divergence | `market_price_snapshots` | **todo** | **only 2026-07 onward** -- unusable historically |

## 9. Play-by-play derived

504,231 plays, currently zero features.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| quarter-by-quarter scoring profile | `game_plays` | **todo** | none |
| largest run / lead changes | `game_plays` | **todo** | none |
| clutch performance (last 5 min, within 5) | `game_plays` | **todo** | none |
| scoring by period, rolling | `game_plays` | **todo** | none |
| player-level PBP | `game_plays` | **blocked** | **no player id on plays** -- names are free text only |

## 10. Context

| Feature | Source | Status | Hazard |
|---|---|---|---|
| attendance, rolling | `games.attendance` | **todo** | none |
| venue (neutral-site detection) | `games.venue_name` | **todo** | none |
| officiating crew foul tendency | `game_officials` + box | **todo** | crew stats must be prior-game only; 3 games have no officials |

---

## Suggested order

1. **Multi-window team form** (§2). Highest value per hour -- the
   machinery exists, it is one window today, and every downstream feature
   benefits.
2. **Opponent completions** (§3). Rest advantage, pace interaction,
   head-to-head. Cheap, and the frame is half-blind without them.
3. **Player rates and role** (§5). Unblocks prop work and roster
   composition.
4. **Roster composition** (§6). The genuinely novel one.
5. **Play-by-play** (§9). Large, untouched, self-contained.
6. **Market features** (§8), in an isolated strategy.

Archetype membership (§4) is deliberately later: it needs prior-season-only
centroids, which is a fitting-discipline problem rather than a feature
problem, and it is easy to get subtly wrong.
