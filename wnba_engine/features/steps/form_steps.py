"""Multi-window team form: the shape of a team's recent record, not just
its level.

`derivation.RollingMeanStep` answers one question -- what has this team
averaged over its last N games -- and FEATURE_ROADMAP.md ss2 calls that
"the thinnest area relative to its value". Everything here answers a
different question about the SAME history:

| step | question |
|---|---|
| `ExpandingMeanStep` | what has it averaged all season, excluding today |
| `ExponentialMeanStep` | what has it averaged, weighting last week over last month |
| `RollingDispersionStep` | how CONSISTENT is it |
| `RollingSlopeStep` | is it improving or declining |
| `SplitRollingMeanStep` | what has it averaged at home / on the road |
| `StreakStep` | how many in a row |
| `MarginProfileStep` | are its games blowouts or coin flips |

Two things a mean cannot express and every one of these can: a team
averaging 82 by scoring 82 every night is not the same team as one
alternating 100 and 64, and a team averaging 82 on the way up is not the
same team as one averaging 82 on the way down. Both are invisible to
`points_scored_mean_5` and both are ordinary basketball knowledge.

Every step here is WINDOWED except `MarginProfileStep`, which is
row-local by construction because it only classifies the row's own
margin. The windowed ones all iterate through `_windowing.trailing_walk`,
which appends a row's observation to its group's history only AFTER that
row has been summarised -- so, exactly as in `RollingMeanStep`, there is
no ordering of the loop in which a row can enter its own window.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import RowMapStep, WindowedStep
from wnba_engine.features.steps._windowing import (
    WINDOW_COUNT_SUFFIX,
    WINDOW_END_SUFFIX,
    finalise,
    mean_of,
    numeric,
    trailing_walk,
)

#: A margin at or above this counts as a blowout. Verified against this
#: database on 2026-08-02: across 1,293 final regular-/post-season games
#: the absolute margin has median 10 and 75th percentile 16, and 28.6% of
#: games are decided by 15 or more. So 15 sits at roughly the top
#: quartile -- a threshold that fires often enough to have a rate worth
#: rolling, and rarely enough to still mean something.
BLOWOUT_MARGIN = 15
#: A margin at or below this counts as a close game. 25.5% of games in
#: the same query land here, which makes the two flags near-symmetric
#: quartiles of the same distribution rather than two arbitrary numbers.
CLOSE_MARGIN = 5


def _observer(columns: Sequence[str]):
    """Remember exactly `columns` from a row, and nothing else.

    Narrowing the observation is deliberate: a history holding whole rows
    would let a summariser reach a column its step never declared it
    reads, which is precisely the drift the guard exists to prevent one
    level up.
    """

    def observe(row: Row) -> dict[str, object]:
        return {column: row.get(column) for column in columns}

    return observe


@dataclass(frozen=True, slots=True)
class ExpandingMeanStep(WindowedStep):
    """Season-to-date mean, EXCLUDING the current game.

    The direct counterpart to FEATURE_ROADMAP.md's second rule: anything
    phrased as "this season's X" contains the game being predicted.
    `SeasonToDateStep` already accumulates record this way; this does the
    same for arbitrary numeric columns, so "this team's season scoring
    average going in" becomes expressible without an `AVG() GROUP BY
    season` that folds the target game into its own feature.

    Complements rather than replaces the rolling windows: an expanding
    mean is the lowest-variance estimate available and the slowest to
    notice that anything has changed, which is why `team_form_multi`
    ships it alongside 5-, 10- and 20-game windows rather than instead of
    them.

    Season is part of the accumulator key, so a new season starts empty.
    Carrying 2025's average into a 2026 opener would describe a roster
    that no longer exists.
    """

    value_columns: tuple[str, ...]
    group_by: tuple[str, ...] = ("team_id",)
    season_column: str = "season"
    label: str = "season_mean"

    def __post_init__(self) -> None:
        if not self.value_columns:
            raise StepContractError("expanding mean step needs at least one value column")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{column}_season_mean" for column in self.value_columns)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                *self.output_columns,
                f"{self.label}{WINDOW_COUNT_SUFFIX}",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(frame, (*self.group_by, self.season_column, *self.value_columns))
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=(*self.group_by, self.season_column),
            observe=_observer(self.value_columns),
        ):
            cell: dict[str, object] = {
                output: mean_of(numeric(past, column))
                for column, output in zip(self.value_columns, self.output_columns, strict=True)
            }
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = len(past)
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max((at for at, _ in past), default=None)
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class ExponentialMeanStep(WindowedStep):
    """Exponentially-weighted mean of prior games.

    A rolling mean gives the game 5 back exactly the weight it gives
    yesterday's, then drops it entirely at game 6. Neither cliff
    corresponds to anything about basketball. An exponential weighting
    decays smoothly, which is the usual answer for a quantity that drifts
    -- a rotation settling, a scheme changing -- rather than jumping.

    The half-life is in GAMES, not days. Days would be the more physical
    unit, but WNBA schedule density varies enough (an All-Star break is
    ~10 days, a mid-season stretch is games every other day) that a
    day-based half-life silently reweights the same 10 games differently
    depending on when in the season they happened. Games is the unit the
    5/10/20 windows already use, so the two are comparable.

    Weights are NORMALISED over the observations that actually exist, so
    a team's second game of the season gets its first game's value rather
    than a value shrunk toward zero by the missing history. Nulls are
    skipped for the same reason `RollingMeanStep` skips them: `pace` is
    null wherever balldontlie has no advanced-stats row, and a zero there
    is a claim nobody made.

    THE WINDOW CROSSES SEASONS BY DEFAULT, and that is a decision worth
    challenging. It matches `RollingMeanStep`, which is also a pure
    trailing-N-games statistic and also does not reset -- as opposed to
    `ExpandingMeanStep` and `StreakStep`, which are explicitly
    season-scoped and do. The cost is bounded and computable: at a
    half-life of 5 games, observations more than one WNBA season back
    (~40 games) carry 0.5**8 = 0.4% each and about 3% of the total weight
    between them. The benefit is that a season opener gets a decayed
    prior instead of a null, which is the whole reason to prefer a decay
    over a hard window. Pass `season_column="season"` for the resetting
    variant; it is one argument, and it is not the default because
    silently discarding the prior is the larger of the two errors.
    """

    value_columns: tuple[str, ...]
    half_life_games: float = 5.0
    group_by: tuple[str, ...] = ("team_id",)
    #: None keeps one continuous history per group; naming a column adds
    #: it to the accumulator key so each season starts empty. See the
    #: class docstring for why crossing is the default.
    season_column: str | None = None
    label: str = "ewm"
    #: Contributions below this weight are dropped. The tail of a decaying
    #: series is unbounded, and summing it exactly would make the step
    #: O(games^2); at 1e-6 the truncation is ~20 half-lives back and moves
    #: no output by a meaningful amount.
    weight_floor: float = 1e-6

    def __post_init__(self) -> None:
        if not self.value_columns:
            raise StepContractError("exponential mean step needs at least one value column")
        if self.half_life_games <= 0:
            raise StepContractError(
                f"half life must be > 0 games, got {self.half_life_games}"
            )

    @property
    def name(self) -> str:
        return self.label

    @property
    def decay(self) -> float:
        """Per-game weight ratio: 0.5 ** (1 / half_life)."""
        return 0.5 ** (1.0 / self.half_life_games)

    @property
    def output_columns(self) -> tuple[str, ...]:
        suffix = f"{self.half_life_games:g}".replace(".", "_")
        return tuple(f"{column}_ewm_{suffix}" for column in self.value_columns)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                *self.output_columns,
                f"{self.label}{WINDOW_COUNT_SUFFIX}",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    @property
    def effective_lookback(self) -> int:
        """How many games back the weight floor actually reaches.

        Reported as `<label>__window_games` (capped by the history that
        exists) rather than the raw length of the history. The raw length
        would say 225 for a late-2026 game and mean nothing -- the other
        `__window_games` columns in this package answer "how many
        observations went into this number", and this one has to answer
        the same question to be comparable to them.
        """
        return int(math.ceil(math.log(self.weight_floor) / math.log(self.decay)))

    def _weighted(self, past: Sequence[tuple[object, object]], column: str) -> float | None:
        """Most recent observation first, weight decaying backwards."""
        total = 0.0
        weights = 0.0
        weight = 1.0
        for _, observation in reversed(past):
            assert isinstance(observation, dict)
            value = observation.get(column)
            if value is not None:
                total += weight * float(value)  # type: ignore[arg-type]
                weights += weight
            weight *= self.decay
            if weight < self.weight_floor:
                break
        return total / weights if weights else None

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        needed = (*self.group_by, *self.value_columns)
        self._require_columns(
            frame, needed if self.season_column is None else (*needed, self.season_column)
        )
        key_columns = (
            self.group_by if self.season_column is None else (*self.group_by, self.season_column)
        )
        lookback = self.effective_lookback
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=key_columns,
            observe=_observer(self.value_columns),
        ):
            contributing = past[-lookback:]
            cell: dict[str, object] = {
                output: self._weighted(past, column)
                for column, output in zip(self.value_columns, self.output_columns, strict=True)
            }
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = len(contributing)
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max((at for at, _ in past), default=None)
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class RollingDispersionStep(WindowedStep):
    """Sample standard deviation over the previous N games -- consistency.

    Two teams with identical `points_scored_mean_10` are not the same
    team if one scored 82 ten times and the other alternated 100 and 64.
    The mean cannot express that and this is the cheapest thing that can.

    Standard deviation rather than variance because it is on the data's
    own scale -- "this team's scoring swings by 9 points" is directly
    comparable to a 9-point line, and squared points are not. The two
    carry identical information, so nothing is lost by choosing the
    legible one.

    SAMPLE standard deviation (n-1). Prior games are a sample of the
    team's behaviour, not the population of it, and the population
    formula is biased low exactly where this matters most -- the 2- and
    3-game windows early in a season. Fewer than two contributing
    observations gives None, because a single number has no spread and
    0.0 would read as "perfectly consistent".
    """

    value_columns: tuple[str, ...]
    window: int
    group_by: tuple[str, ...] = ("team_id",)
    label: str = "dispersion"

    def __post_init__(self) -> None:
        if self.window < 2:
            raise StepContractError(
                f"a dispersion window needs at least 2 games, got {self.window}"
            )
        if not self.value_columns:
            raise StepContractError("dispersion step needs at least one value column")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{column}_sd_{self.window}" for column in self.value_columns)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                *self.output_columns,
                f"{self.label}{WINDOW_COUNT_SUFFIX}",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(frame, (*self.group_by, *self.value_columns))
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=self.group_by,
            observe=_observer(self.value_columns),
        ):
            contributing = past[-self.window :]
            cell: dict[str, object] = {
                output: _stddev(numeric(contributing, column))
                for column, output in zip(self.value_columns, self.output_columns, strict=True)
            }
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = len(contributing)
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max(
                (at for at, _ in contributing), default=None
            )
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class RollingSlopeStep(WindowedStep):
    """Least-squares slope over the previous N games -- form TREND.

    A team averaging 82 on the way up and one averaging 82 on the way
    down are different teams facing tonight's line, and every mean --
    rolling, expanding, exponential -- reports them identically.

    The regressor is the observation's POSITION in the window (0, 1, 2,
    ...), not elapsed days. Two reasons, and the first is the honest one:
    an unequally-spaced regression would give a game after a 10-day break
    enormous leverage purely because of the calendar, which is a
    statement about the schedule rather than about the team. The second
    is that positions keep the units interpretable -- the output is
    "points per game of trend", directly comparable across teams whose
    schedules differ.

    Positions are assigned among the CONTRIBUTING (non-null) observations
    rather than among all N, so a `pace`-less game compresses the window
    instead of leaving a hole that fakes a flat stretch.

    Fewer than two contributing observations gives None. A slope through
    one point is not zero, it is undefined, and 0.0 would read as
    "definitely not trending".
    """

    value_columns: tuple[str, ...]
    window: int
    group_by: tuple[str, ...] = ("team_id",)
    label: str = "slope"

    def __post_init__(self) -> None:
        if self.window < 2:
            raise StepContractError(f"a slope window needs at least 2 games, got {self.window}")
        if not self.value_columns:
            raise StepContractError("slope step needs at least one value column")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{column}_slope_{self.window}" for column in self.value_columns)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                *self.output_columns,
                f"{self.label}{WINDOW_COUNT_SUFFIX}",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(frame, (*self.group_by, *self.value_columns))
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=self.group_by,
            observe=_observer(self.value_columns),
        ):
            contributing = past[-self.window :]
            cell: dict[str, object] = {
                output: _slope(numeric(contributing, column))
                for column, output in zip(self.value_columns, self.output_columns, strict=True)
            }
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = len(contributing)
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max(
                (at for at, _ in contributing), default=None
            )
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class SplitRollingMeanStep(WindowedStep):
    """Rolling mean over prior games matching a SPLIT -- home only, road only.

    Home/road is the split ROADMAP.md Phase 2 names, and it is not
    reducible to `home_away_is_home` next to a combined average: a team
    can be +8 at home and -6 on the road while its overall mean says +1,
    and tonight it is playing one of the two.

    FEATURE_ROADMAP.md flags the hazard directly -- "thin samples early
    in a season". A team's fifth home game is its tenth game overall, so
    a 10-game home window is nearly a season-to-date average in May and a
    genuine window in August. `<label>__window_games` reports the real
    contribution for exactly that reason, and it is not optional
    bookkeeping: without it a 10-game home average computed over 2 games
    is indistinguishable from one computed over 10.

    The split column is compared with `==` against a declared value
    rather than being truthy-tested, so `SplitRollingMeanStep(...,
    split_value=False)` means "road games" and not "everything falsy",
    which would also swallow nulls.
    """

    value_columns: tuple[str, ...]
    window: int
    split_column: str
    split_value: object
    suffix: str
    group_by: tuple[str, ...] = ("team_id",)
    label: str = "split"

    def __post_init__(self) -> None:
        if self.window < 1:
            raise StepContractError(f"split window must be >= 1, got {self.window}")
        if not self.value_columns:
            raise StepContractError("split step needs at least one value column")
        if not self.suffix:
            raise StepContractError("split step needs a suffix to name its columns")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(
            f"{column}_mean_{self.window}_{self.suffix}" for column in self.value_columns
        )

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                *self.output_columns,
                f"{self.label}{WINDOW_COUNT_SUFFIX}",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(
            frame, (*self.group_by, self.split_column, *self.value_columns)
        )
        remembered = (*self.value_columns, self.split_column)
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=self.group_by,
            observe=_observer(remembered),
        ):
            matching = [
                entry
                for entry in past
                if isinstance(entry[1], dict)
                and entry[1].get(self.split_column) == self.split_value
            ]
            contributing = matching[-self.window :]
            cell: dict[str, object] = {
                output: mean_of(numeric(contributing, column))
                for column, output in zip(self.value_columns, self.output_columns, strict=True)
            }
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = len(contributing)
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max(
                (at for at, _ in contributing), default=None
            )
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class StreakStep(WindowedStep):
    """Signed win/loss streak going INTO this game.

    +3 means three straight wins, -3 means three straight losses, 0 means
    no prior game in scope. One signed column rather than a pair, because
    a team cannot simultaneously be on a win streak and a loss streak and
    two columns would spend a degree of freedom asserting that.

    Season is part of the key by default. A streak carried from the last
    game of 2025 into the 2026 opener describes a roster that has since
    turned over and a gap of seven months; if a caller genuinely wants
    cross-season continuity, `season_column=None` expresses it explicitly
    rather than as an oversight.

    A null `won` breaks the streak to 0 rather than being skipped. `won`
    is null only when the game has no score, and treating an unknown
    result as continuing a streak would assert something the data does
    not say.
    """

    group_by: tuple[str, ...] = ("team_id",)
    season_column: str | None = "season"
    outcome_column: str = "won"
    label: str = "streak"

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return ("win_streak",)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=("win_streak", f"{self.label}{WINDOW_END_SUFFIX}"),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        needed = (*self.group_by, self.outcome_column)
        self._require_columns(
            frame, needed if self.season_column is None else (*needed, self.season_column)
        )
        key_columns = (
            self.group_by if self.season_column is None else (*self.group_by, self.season_column)
        )
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=key_columns,
            observe=_observer((self.outcome_column,)),
        ):
            cells[index] = {
                "win_streak": _streak_from(past, self.outcome_column),
                f"{self.label}{WINDOW_END_SUFFIX}": past[-1][0] if past else None,
            }
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class MarginProfileStep(RowMapStep):
    """Classify the row's OWN margin as blowout / close.

    Row-local and therefore incapable of leaking, but read the caveat:
    these three columns describe the game being predicted, exactly like
    `derivation.TARGET_COLUMNS` do. They exist so a rolling mean over
    them becomes a RATE -- "this team has blown someone out in 40% of its
    last 10" -- and that rolled column is the feature. Feed the raw flags
    to a model and you have told it who won.

    Thresholds are declared as module constants with the query that
    justified them; see BLOWOUT_MARGIN.
    """

    margin_column: str = "point_margin"
    step_name: str = "margin_profile"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return ("is_blowout_win", "is_blowout_loss", "is_close_game")

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        margin = row.get(self.margin_column)
        if margin is None:
            # Null, not False: a game with no score is not a game that
            # was close, and a rolling rate must skip it rather than
            # count it as a non-blowout.
            return dict.fromkeys(self.output_columns)
        value = int(margin)  # type: ignore[arg-type]
        return {
            "is_blowout_win": value >= BLOWOUT_MARGIN,
            "is_blowout_loss": value <= -BLOWOUT_MARGIN,
            "is_close_game": abs(value) <= CLOSE_MARGIN,
        }


def _stddev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _slope(values: Sequence[float]) -> float | None:
    """OLS slope of `values` against their own ordinal positions."""
    n = len(values)
    if n < 2:
        return None
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    denominator = sum((x - mean_x) ** 2 for x in range(n))
    if denominator == 0:  # pragma: no cover -- n >= 2 makes this impossible
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values))
    return numerator / denominator


def _streak_from(past: Sequence[tuple[object, object]], column: str) -> int:
    """Count backwards from the most recent result while it repeats."""
    streak = 0
    for _, observation in reversed(past):
        assert isinstance(observation, dict)
        outcome = observation.get(column)
        if outcome is None:
            break
        won = bool(outcome)
        if streak == 0:
            streak = 1 if won else -1
            continue
        if won and streak > 0:
            streak += 1
        elif not won and streak < 0:
            streak -= 1
        else:
            break
    return streak


__all__ = [
    "BLOWOUT_MARGIN",
    "CLOSE_MARGIN",
    "ExpandingMeanStep",
    "ExponentialMeanStep",
    "MarginProfileStep",
    "RollingDispersionStep",
    "RollingSlopeStep",
    "SplitRollingMeanStep",
    "StreakStep",
]
