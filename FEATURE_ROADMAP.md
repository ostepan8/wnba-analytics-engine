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
| `team_form_multi` | 29 | 111 |
| `team_matchup` | 23 | 80 |
| `team_style` | 13 | 80 |
| `player_form` | 9 | 46 |
| `player_rates` | 17 | 76 |

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
| rest ADVANTAGE vs opponent | `games` | done (ss3) | needs opponent mirror -- AND inherits `rest_days`' cross-season gap; see `RestAdvantageStep` |
| time-zone crossings | `games.venue_name` | **todo** | venue -> timezone mapping does not exist yet |

## 2. Team form, multi-window

Currently one window (5 games) and one statistic (mean). This is the
thinnest area relative to its value.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| rolling mean, 5 | `team_game_stats` | done | none |
| rolling mean, 10 / 20 / season-to-date | same | done | none |
| exponentially weighted form | same | done | crosses seasons by default -- see `ExponentialMeanStep` |
| rolling **variance** (consistency) | same | done | emitted as SAMPLE stddev, on the data's own scale |
| form **trend** (slope over window) | same | done | regressed on window POSITION, not elapsed days |
| home-only / road-only splits | same | done | thin samples early in a season -- `split_*__window_games` reports the real count |
| win / loss streak length | `games` | done | resets per season by default |
| margin distribution (blowout rate) | `games` | done | the raw flags are TARGETS; the rolled rate is the feature |

All of the above live in the `team_form_multi` strategy
(`steps/form_steps.py`), which is `team_form` plus an eleven-step
multi-window block. Kept separate so the cheap frame stays cheap -- see
that factory's docstring for the argument and the counter-argument.

## 3. Opponent and matchup

The frame carried `opponent_team_id` and derived nothing from it until
recently. `OpponentFormStep.mirroring()` now mirrors any windowed step.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| opponent rolling form / pace | mirror | done | mirrors pair with their source step |
| opponent season-to-date | mirror | done | same |
| head-to-head history this season | `games` | done | must exclude the current game |
| head-to-head, multi-season | `games` | done | same; also confounded with quality -- keep `*_margin_mean_prior` next to overall form |
| opponent defensive strength by position | `player_game_stats` | **blocked** | `players.position` is a CURRENT-STATE UPSERT, not a stable label -- see below |
| pace INTERACTION (both fast / both slow) | mirror | done | no threshold: a fitted one is cross-sectional, a hard-coded one is an era claim |

Rest advantage, pace interaction and both head-to-head horizons live in
the `team_matchup` strategy (`steps/matchup_steps.py`).

**Why positional defence is blocked, not merely unbuilt.** The row above
reads as a mapping problem ("`players.position` is present"). It is a
provenance problem. `entity_repo.resolve_or_create_player` runs
`UPDATE players SET full_name = %s, position = %s` on EVERY box-score
ingest, so `position` is a current-state upsert in exactly the sense
`team_standings` is -- and `players` carries no `captured_at` to anchor
it. The values confirm it: the table holds `G` and `Guard`, `F` and
`Forward`, `C` and `Center` for the same three concepts, which is
last-writer-wins across providers rather than a vocabulary. 130 of 1,005
players read `Not Available`.

The label is not outcome-bearing, so this is weaker than the standings
trap -- a wrong position bucket adds noise rather than smuggling a
result. But it has no as-of anchor and its bucketing convention drifts,
so it cannot ship under this package's rules without either a
`player_positions_history` table or a position INFERRED from box-score
behaviour. The latter is archetype work, which the roadmap already defers
for the same reason.

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
| per-36 rates, rolling | `player_game_stats` | done | ratio OF SUMS, never mean of ratios (see MODELING_FINDINGS) |
| usage / TS% / PIE, rolling | `player_advanced_stats` | done | the TEXT `minutes` is NOT read -- rates are minutes-weighted by the box-score integer |
| role: minutes share of team | `player_game_stats` | done | THIS game's share is not computable and the guard is right to refuse it |
| starter rate, rolling | `player_game_stats` | done | none -- `RollingMeanStep` over a boolean is already a rate |
| player style vector, rolling | both | done | the per-36 + share + weighted-rate block IS the trailing vector; dimensions match `analysis/style.py` |
| player uniqueness vs league | derived | **todo** | population must be prior seasons only -- a fitting-discipline problem, deferred with archetypes |
| **projected minutes** | none yet | **blocked** | needs lineup news -- the single highest-value missing input |

Everything above except uniqueness lives in the `player_rates` strategy
(`steps/player_steps.py`). Three ratio shapes, all taking the ratio of
SUMS: `RollingRateStep` (per-36 and shot-mix shares),
`RollingWeightedMeanStep` (provider-computed rates, minutes-weighted) and
`RollingShareStep` (a denominator that lives on sibling rows).

Two things found while building it, both pre-existing on `main`:

- **`load_player_games` filtered on `start_time` while declaring
  `result_known_at` as its anchor**, so a game that tipped off before the
  boundary and finished after it was admitted and then rejected by the
  guard. The README's own example
  (`--as-of 2026-07-29 --strategy player_form`) raised `LeakageError`.
  Fixed to the `COALESCE(final_observed_at, start_time + margin)` form the
  team-game query always used.
- **A rolling window excluded the current ROW but not a SIMULTANEOUS
  one.** Player 137 has ESPN box-score rows in two games both tipping off
  at 2024-08-23T23:30Z -- one collision in 31,340 rows, and enough to make
  a per-player window publish a window end equal to its own tip-off.
  `_windowing.trailing_walk` now holds an observation until the walk
  reaches a strictly later instant; `RollingMeanStep` and
  `SeasonToDateStep` were moved onto it.

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

Built as two strategies, `team_market` (game grain) and `player_market`
(player grain), both in `wnba_engine/features/steps/market_steps.py`. Kept
separate from the basketball strategies for the reason stated above, not
for cost.

| Feature | Source | Status | Hazard |
|---|---|---|---|
| consensus line / total, de-vigged | `sportsbook_game_odds` | **done** | de-vig PER BOOK before averaging; a mean of raw implied probabilities is not a probability |
| cross-book dispersion | same | **done** | meaningless unless the de-vig happens first |
| line movement, open -> current | same | **done** | none; the opening quote is knowable at every later instant |
| implied win probability | same | **done** | none |
| prop line vs rolling mean | `sportsbook_player_prop_odds` | **done** | player grain (`player_market`); pair against a ROLLING mean, never a season average |
| prediction-market divergence | `polymarket_trades` | **done** | ~~only 2026-07 onward~~ -- **superseded**: on-chain fills go back to 2024-09, so the historical limit is gone |

Two traps found while building it, both of which produced a frame that
looked correct:

- **`captured_at` is each BOOK's own `last_update`**, so books almost never
  share an instant. Bucketing by exact timestamp gave a median `book_count`
  of 1 and an all-null dispersion. The consensus has to be a running one:
  each book's latest quote as of each moment.
- **An as-of anchor named only in `provenance` arrives NULL.**
  `AsOfJoinStep` copies the chosen cells verbatim, and the guard reads a
  null anchor as "no observation" and passes -- so the check silently
  checked nothing. The anchor must be written into the cells.

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
