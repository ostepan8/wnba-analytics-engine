# `wnba_engine/features/`

A composable preprocessing layer that cannot read the future.

Feature extraction serves both the rules-based insights of ROADMAP.md
Phase 2 and any later modelling decision. This package is the *extraction*
half only -- it computes situational context (home/road, rest,
back-to-backs, pace, rolling form) at a stated point in time. It is not a
model pipeline, and per `AGENTS.md` it should not be presented as one.

```python
from datetime import UTC, datetime

from wnba_engine.features import FeatureContext, PostgresRowSource, strategies

context = FeatureContext(as_of=datetime(2025, 8, 1, tzinfo=UTC), seasons=(2025,))
with db.connection() as conn:
    pipeline = strategies.build("team_form", PostgresRowSource(conn))
    frame = pipeline.run(context=context)

frame.to_columns()   # -> dict[str, list], the one-line bridge to pandas/polars
```

Or from the CLI:

```bash
uv run wnba-engine build-features --as-of 2025-08-01 --strategy team_form --season 2025
uv run wnba-engine build-features --as-of 2026-07-29 --strategy player_form --out /tmp/props.csv
```

---

## The leakage contract

**Nothing a feature is computed from may have been unobservable at the
time.** That splits into two rules, and the second is the one naive
implementations miss.

| Rule | Checked against | Catches |
|---|---|---|
| **Frame-level** -- every source timestamp `<= context.as_of` | the boundary | a loader missing its `WHERE`, a snapshot from after the boundary |
| **Row-level** -- every backward-looking window ends strictly before the row's own tip-off | `games.start_time` on that row | a rolling average including its own game, a season aggregate spanning the target date, a standings snapshot attached to an earlier game |

Both are enforced by `LeakageGuard`, which runs after **every** step, not
once at the end. Per-step means the error names the culprit instead of
telling you the output is contaminated.

Three further properties make the checks meaningful rather than
decorative:

1. **A step that cannot declare provenance cannot pass.** A frame holding
   rows but declaring no as-of anchor raises `UndeclaredProvenanceError`.
   Unprovable is treated as unsafe, because the cheapest way to defeat a
   timestamp check is to emit no timestamp.
2. **A step may add only the columns it declared.** Drift between
   `StepProvenance.adds_columns` and reality is a `StepContractError`. A
   step that can add a column unnoticed can add a leaky one.
3. **Known-leaky sources are refused at the SQL.**
   `wnba_engine/repositories/feature_repo.py` scans every feature query
   and rejects `team_standings`, `season_awards`, `players.age`, and
   `players.jersey_number` by name, with the reason. It also refuses any
   point-in-time query that does not reference `%(as_of)s`.

### What the guard does NOT catch

Worth knowing before trusting it further than it deserves.

- **A lying step.** `source_tables` is a declaration; a determined author
  can read a forbidden table through a view, dynamic SQL, or a raw cursor
  and the identifier scan will not see it. The scan converts the *likely*
  failure (someone writes the obvious query) into a loud one; it is not a
  sandbox.
- **Cross-sectional leakage from fitted encoders.** `FitScaleStep` fits
  on the frame, which is time-safe -- no post-boundary observation can
  influence a parameter -- but a z-score's mean includes the row being
  scaled. Use the explicitly-parameterised `ScaleStep` where that matters.
- **Semantic wrongness inside a correct window.** A backward window over
  the wrong grouping key (player instead of team for rest) is verifiably
  backward-looking and still wrong. Unit tests, not the guard.
- **Result-timing precision.** `games` has no "when did we learn the
  score" column, so the loaders approximate it with a 4-hour
  `completion_margin` after tip-off. A game that ran long and was ingested
  slowly could in principle still slip in. **The real fix is a
  `result_known_at` column on `games`**, which is a schema change this
  layer did not make.
- **Anything outside a declared anchor.** Only columns registered in
  `as_of_columns` / `window_end_columns` are timestamp-checked. That is
  why the base classes register them for the subclass rather than trusting
  it to remember.

---

## Architecture

```
context.py      FeatureContext -- as_of + scope. Passed to every step.
frame.py        FeatureFrame -- typed rows + provenance declarations.
provenance.py   StepKind + StepProvenance -- what a step must declare.
step.py         PreprocessingStep protocol + one base class per kind.
guard.py        LeakageGuard -- structural, provenance, boundary, window.
pipeline.py     Pipeline -- immutable ordered stack + with_step/without/...
source.py       FeatureRowSource protocol; Postgres and in-memory impls.
strategies.py   Named, pre-composed pipelines.
steps/          loading | cleaning | filtering | derivation | form
                matchup | player | style | market | encoding
_windowing.py   the one invariant every WINDOWED step shares (see below)
```

`FeatureFrame` is a tuple of `MappingProxyType` rows plus three
declarations (`as_of_columns`, `window_end_columns`, `event_time_column`).
Deliberately **not** pandas: this repo's dependency list is five packages,
the frames are small (~2,700 team-game rows, ~31k single-source
player-game rows), and per-row timestamp inspection is a loop over dicts
rather than dtype archaeology. `to_columns()` keeps the door open.

### Step kinds

The kind is not a label -- it determines both what `apply` is *able* to
do and what the guard demands afterwards.

| Kind | Base class | Sees | Rows | Must declare |
|---|---|---|---|---|
| `SOURCE` | `SourceStep` | nothing | creates | as-of anchor + event-time column |
| `JOIN` | `AsOfJoinStep` | one row at a time | unchanged | the joined timestamp (checked per row) |
| `TIME_INVARIANT` | `TimeInvariantJoinStep` | one row at a time | unchanged | a written `justification` |
| `ROW_LOCAL` | `RowMapStep` | **one row** | unchanged | its columns |
| `WINDOWED` | `WindowedStep` | the whole frame | unchanged | a `window_end_column` |
| `FILTER` | `FilterStep` | one row at a time | may only shrink | nothing (adds no columns) |
| `FITTED` | `FittedStep` | the whole frame | unchanged | its columns |

The teeth are in the two middle rows. `RowMapStep.transform` is handed a
single row and has **no route to another**, so "this feature is row-local"
is guaranteed by the signature. Anything genuinely needing cross-row
context must be `WINDOWED`, and a windowed step must publish where its
window stopped -- which the guard then checks. `StepProvenance` validates
these combinations in `__post_init__`, and strategies are composed at
import time, so a mis-declared step is an `ImportError`, not a surprise
three hours into a backfill.

### The one thing every windowed step gets right the same way

`steps/_windowing.py::trailing_walk` walks the frame in event order and
hands each row **its group's prior observations**, appending the row's
own observation only after the consumer resumes:

```python
for index, row, past in trailing_walk(frame, self.name, group_by=("team_id",),
                                      observe=_observer(("points_scored",))):
    cells[index] = summarise(past)     # `past` cannot contain `row`
```

That is the structural reason a row can never enter its own window, and
it is the single most-repeated piece of logic here -- ten windowed steps
across two modules need it. It lives in one function because the tenth
copy is the one that gets it backwards, and because the failure is a
value rather than a crash.

The guard does not take the helper's word for it: every windowed step
still publishes a window end, and that end is still compared to the
row's own tip-off. `tests/unit/features/test_leakage_guard.py` carries a
deliberately-leaky variant of each family (rolling, expanding, slope,
split, streak, per-36 rate, minutes share, head-to-head, standings join)
that must be rejected.

It also carries the one case where "append after emitting" is not enough.
An observation is held until the walk reaches a STRICTLY LATER event
time, because two rows sharing an instant would otherwise enter each
other's windows. That is not theoretical: player 137 has ESPN box-score
rows in two games both tipping off at 2024-08-23T23:30Z -- one collision
in 31,340 rows, and enough to make a per-player rolling window publish a
window end equal to its own tip-off.

---

## Adding a step

1. Pick the narrowest kind that can do the job. If a `RowMapStep` will
   work, it is the right answer -- it is the only kind that cannot leak.
2. Subclass the matching base as a `@dataclass(frozen=True, slots=True)`
   holding its config.
3. Implement `name` and `provenance` as properties. Properties rather than
   fields because configurable steps derive their column names from
   config, and a field would let the declaration drift.
4. Implement the one abstract hook (`transform` / `compute` / `keep` /
   `fetch` / `observations`).
5. Unit test the numbers, and if the step is windowed, assert what it
   returns for the FIRST row of a group -- that is where an off-by-one
   shows up as a value instead of a crash.

```python
@dataclass(frozen=True, slots=True)
class OpponentStrengthStep(RowMapStep):
    """Why this exists and what evidence backs the definition."""

    step_name: str = "opponent_strength"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=("opponent_strength",))

    def transform(self, row: Row, context: FeatureContext) -> Row:
        return {"opponent_strength": ...}
```

Reading a new table means a new function in `feature_repo.py`, called
through `execute_point_in_time` (or `execute_time_invariant` with a
justification). Declare its column tuple as a module constant and point
the step's `adds_columns` at it -- the guard then keeps the SQL and the
declaration in sync for you.

## Market features are quarantined on purpose

`team_market` is the only strategy carrying `sportsbook_game_odds` or
`polymarket_trades` columns, and that separation is a containment decision
rather than a cost one. The line is the best single forecast of a game in
existence, so a frame holding it beats every basketball feature here on any
metric while teaching nothing -- it is a copy of someone else's model. Anyone
comparing strategies has to be unable to include it by accident.

What it IS for: measuring whether anything else in this package adds
information the market has not already priced. `MODELING_FINDINGS.md` records
that nothing has yet.

Two traps that both produced a frame which looked fine:

- `sportsbook_game_odds.captured_at` is each BOOK's own `last_update`, so
  books almost never share an instant. A consensus bucketed by exact
  timestamp is usually one book (median `book_count` of 1) with a null
  dispersion. `JoinMarketOddsStep` therefore keeps a running consensus.
- An as-of anchor declared in `provenance.as_of_columns` but never written
  into the joined cells arrives NULL, and **the guard reads a null anchor as
  "no observation" and passes**. Declaring the anchor is not enough; the
  step has to emit it.

## Adding a strategy

Write a factory taking a `FeatureRowSource`, compose it from an existing
one where possible, and register it in `STRATEGIES`. The CLI's
`--strategy` choices come from that dict; nothing else needs to change.

```python
def defensive_form(source: FeatureRowSource) -> Pipeline:
    return situational_baseline(source).renamed("defensive_form").with_steps((...,))
```

**Order is semantic.** Filters that decide *what counts as a game*
(franchise, season type) must run BEFORE the windowed steps, or an
exhibition against a national team ends up inside a "last 5 games"
average. Filters that decide what counts as a usable *row* (minimum
minutes) run after, because a garbage-time cameo is still a game the team
played. `Pipeline.insert_after` exists so adding a step forces a choice of
position rather than defaulting to the end.

## Swapping at the call site

Every mutator returns a new `Pipeline`; the shared factory output is never
modified.

```python
base    = strategies.build("team_form", source)
cheap   = base.without("rolling_form_5").without("join_standings_snapshot")
window3 = base.replace_step("rolling_form_5", RollingMeanStep(..., window=3,
                                                              label="rolling_form_5"))
```

---

## Data facts that shaped this package

Each of these changed the design, and each is verified against this
database (see `DATA_INVENTORY.md`).

- **`team_standings` is a current-state upsert.** Reading it for a 2023
  game returns 2026 standings. Refused by name; `team_standings_history`
  is used instead.
- **`team_standings_history` starts at 2026-07-09.** Every 2022-2025 game
  therefore has NO standings feature, and that is the honest answer --
  back-filling from `team_standings` would invent it.
- **A "latest snapshot at as_of" join is still a leak.** It attaches July
  standings to a May game. Hence `AsOfJoinStep`, which joins per row.
- **`player_game_stats` has two sources.** ESPN and balldontlie rows exist
  for the same games. Omitting the filter doubles every player's game
  count and halves every average.
- **`games.start_time` is UTC, and evening tip-offs land on the next UTC
  date.** Back-to-backs are therefore defined by elapsed hours (< 36h),
  not by consecutive dates.
- **`pace` is null wherever balldontlie has no advanced-stats row.**
  Rolling means skip nulls and report `__window_games` so a "5-game
  average" over 2 games is legible as one.
- **NUMERIC arrives as `decimal.Decimal`,** which raises `TypeError` on
  contact with a float. Coerce before any arithmetic step.
- **`players.age` and `jersey_number` are refreshed on every
  re-ingestion.** Refused; `height`/`weight`/`college` are joined as
  explicitly time-invariant with a written justification.
- **`players.position` is refreshed the same way** --
  `entity_repo.resolve_or_create_player` upserts it on every box-score
  ingest, and the table holds both `G` and `Guard` for the same concept.
  Not refused by name (it is not outcome-bearing), but it has no as-of
  anchor, which is why FEATURE_ROADMAP.md's positional-defence row is
  marked blocked rather than todo.
- **`player_advanced_stats` is balldontlie only and joins onto ESPN box
  scores through our canonical ids.** 28,989 of 31,340 rows match
  (92.5%); the rest get nulls, like `pace` at team grain. The join pins
  `source` explicitly because the table is UNIQUE(game_id, player_id,
  source) and a second provider would double every player-game.
- **`season_awards` is end-of-season ground truth.** Refused entirely.
