"""Player RATES and ROLE, as opposed to player totals.

FEATURE_ROADMAP.md ss5 asks for per-36 rates, usage/TS/PIE, minutes share
and starter rate. All four are ratios, and every one of them has the same
trap, which MODELING_FINDINGS.md already paid to learn:

> (A first attempt scored 8.0045 by averaging ratios rather than taking a
> ratio of sums; `avg(stat/minutes)` is biased upward by low-minute games
> with noisy rates.)

That is a 2.6x worse MAE than the naive baseline, from one line of
arithmetic. So the two windowed steps here are built around the correct
form rather than offering it as an option:

- `RollingRateStep` sums numerators and denominators separately across
  the window and divides ONCE. A 3-minute cameo with 3 points contributes
  3 and 3, not a 36-point-per-36 outlier.
- `RollingWeightedMeanStep` is the same discipline for a quantity that
  arrives already divided. `usage_pct` is a rate the provider computed,
  so it cannot be re-derived from sums -- but a plain mean over it still
  weights a 4-minute appearance equally with a 38-minute one. Weighting
  by minutes is the closest available approximation to the ratio of sums.

`RollingShareStep` is the third shape: a ratio whose denominator lives on
OTHER ROWS -- a player's minutes over their team's minutes. That one
cannot be a rolling mean of a per-game share for a subtler reason than
bias. Computing this game's share requires this game's team total, which
requires the sibling rows of the game being predicted, so the window
would end at the row's own tip-off and the guard would reject it. It is
rejected correctly: tonight's minutes distribution is not knowable before
tonight. The step therefore takes the ratio over PRIOR games directly.

Everything else ss5 asks for is already expressible. Starter rate is
`RollingMeanStep(value_columns=("starter",), ...)` -- a rolling mean over
a boolean IS a rate -- and the rolling player style vector is
`RollingMeanStep` over the advanced columns the loader now brings in,
which is why neither gets a class here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import WindowedStep
from wnba_engine.features.steps._windowing import (
    WINDOW_COUNT_SUFFIX,
    WINDOW_END_SUFFIX,
    chronological,
    finalise,
    trailing_walk,
)

#: Minutes a per-36 rate is expressed over. Named rather than inlined
#: because the same constant appears in analysis/style.py's
#: PLAYER_DIMENSIONS ("pts36", "reb36", ...) and the two must agree if a
#: trailing vector is ever to be compared to a season one.
PER_36 = 36.0


def _usable(past: Sequence[tuple[object, object]], column: str, *, positive: bool) -> int:
    """How many observations carry a usable denominator or weight.

    Counted from the DENOMINATOR alone rather than per numerator, because
    a step emitting several numerators over one denominator must publish
    ONE window count and the denominator is what defines the set of games
    the ratio describes. Counting the last numerator's pairings instead
    would make the reported number depend on the order of value_columns.
    """
    total = 0
    for _, observation in past:
        assert isinstance(observation, dict)
        value = observation.get(column)
        if value is None:
            continue
        if positive and float(value) <= 0:  # type: ignore[arg-type]
            continue
        total += 1
    return total


def _paired(
    past: Sequence[tuple[object, object]], numerator: str, denominator: str
) -> tuple[float, float, int]:
    """(sum numerator, sum denominator, contributing observations).

    An observation counts only when BOTH sides are present. Summing the
    numerator over games where the denominator is missing would inflate
    the rate by whatever those games contributed -- the ratio would stop
    describing any real set of games.
    """
    top = 0.0
    bottom = 0.0
    used = 0
    for _, observation in past:
        assert isinstance(observation, dict)
        a, b = observation.get(numerator), observation.get(denominator)
        if a is None or b is None:
            continue
        top += float(a)  # type: ignore[arg-type]
        bottom += float(b)  # type: ignore[arg-type]
        used += 1
    return top, bottom, used


@dataclass(frozen=True, slots=True)
class RollingRateStep(WindowedStep):
    """Ratio of SUMS over the previous N games, scaled.

    `points` over `minutes` at scale 36 gives points per 36 minutes.
    Scale 1 and a denominator of `field_goals_attempted` gives a shot-mix
    share. Both are the same operation and both must divide once, at the
    end, over the whole window -- see the module docstring for the
    measured cost of doing it the other way.

    The denominator being zero across the whole window gives None, not a
    division error and not zero. A player with no field-goal attempts in
    ten games has no three-point share; asserting 0.0 would say they took
    only twos.

    Nulls in either side drop that observation from BOTH sums, so
    `<label>__window_games` reports the games the ratio actually
    describes rather than the games in the window. That number is worth
    reading here more than anywhere else in the package: a DNP stores
    NULL minutes (db/migrations/0002_box_scores.sql), so an injured
    player's "last 10 games" can legitimately be two.
    """

    value_columns: tuple[str, ...]
    denominator_column: str
    window: int
    scale: float = PER_36
    suffix: str = "per36"
    group_by: tuple[str, ...] = ("player_id",)
    label: str = "rolling_rate"

    def __post_init__(self) -> None:
        if self.window < 1:
            raise StepContractError(f"rate window must be >= 1, got {self.window}")
        if not self.value_columns:
            raise StepContractError("rate step needs at least one numerator column")
        if not self.suffix:
            raise StepContractError("rate step needs a suffix to name its columns")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{column}_{self.suffix}_{self.window}" for column in self.value_columns)

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
            frame, (*self.group_by, self.denominator_column, *self.value_columns)
        )
        remembered = (*self.value_columns, self.denominator_column)
        cells: list[Row | None] = [None] * len(frame.rows)

        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=self.group_by,
            observe=lambda row: {c: row.get(c) for c in remembered},
        ):
            contributing = past[-self.window :]
            cell: dict[str, object] = {}
            for column, output in zip(self.value_columns, self.output_columns, strict=True):
                top, bottom, _ = _paired(contributing, column, self.denominator_column)
                cell[output] = (self.scale * top / bottom) if bottom else None
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = _usable(
                contributing, self.denominator_column, positive=False
            )
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max(
                (at for at, _ in contributing), default=None
            )
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class RollingWeightedMeanStep(WindowedStep):
    """Mean over the previous N games, WEIGHTED by a second column.

    For quantities the provider already divided. `usage_pct`,
    `true_shooting_pct` and `pie` are rates computed by balldontlie from
    inputs this database does not store, so a ratio of sums is not
    available -- but the unweighted mean over them has the same defect a
    ratio of means has, in a milder form: a 4-minute appearance with a
    40% usage rate moves the average exactly as much as a 38-minute one.

    Weighting by minutes recovers most of what the ratio of sums would
    have given, and states plainly which approximation is being made.

    An observation with a null weight, a zero weight, or a null value is
    skipped rather than counted at weight zero -- the two are equivalent
    arithmetically and only the first is legible in
    `<label>__window_games`.
    """

    value_columns: tuple[str, ...]
    weight_column: str
    window: int
    group_by: tuple[str, ...] = ("player_id",)
    label: str = "weighted"

    def __post_init__(self) -> None:
        if self.window < 1:
            raise StepContractError(f"weighted window must be >= 1, got {self.window}")
        if not self.value_columns:
            raise StepContractError("weighted mean step needs at least one value column")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{column}_wmean_{self.window}" for column in self.value_columns)

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
        self._require_columns(frame, (*self.group_by, self.weight_column, *self.value_columns))
        remembered = (*self.value_columns, self.weight_column)
        cells: list[Row | None] = [None] * len(frame.rows)

        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=self.group_by,
            observe=lambda row: {c: row.get(c) for c in remembered},
        ):
            contributing = past[-self.window :]
            cell: dict[str, object] = {}
            for column, output in zip(self.value_columns, self.output_columns, strict=True):
                total, weights, _ = _weighted(contributing, column, self.weight_column)
                cell[output] = (total / weights) if weights else None
            cell[f"{self.label}{WINDOW_COUNT_SUFFIX}"] = _usable(
                contributing, self.weight_column, positive=True
            )
            cell[f"{self.label}{WINDOW_END_SUFFIX}"] = max(
                (at for at, _ in contributing), default=None
            )
            cells[index] = cell
        return finalise(cells, self.name)


def _weighted(
    past: Sequence[tuple[object, object]], value: str, weight: str
) -> tuple[float, float, int]:
    total = 0.0
    weights = 0.0
    used = 0
    for _, observation in past:
        assert isinstance(observation, dict)
        v, w = observation.get(value), observation.get(weight)
        if v is None or w is None:
            continue
        weight_value = float(w)  # type: ignore[arg-type]
        if weight_value <= 0:
            continue
        total += weight_value * float(v)  # type: ignore[arg-type]
        weights += weight_value
        used += 1
    return total, weights, used


@dataclass(frozen=True, slots=True)
class RollingShareStep(WindowedStep):
    """A player's share of their TEAM's total, over the previous N games.

    ROLE, in the sense FEATURE_ROADMAP.md ss5 means it: 30 minutes is a
    different thing on a team playing an eight-woman rotation than on one
    playing eleven, and a raw minutes average cannot tell them apart.

    Two properties are load-bearing and neither is obvious:

    1. IT IS A RATIO OF SUMS, like everything else in this module. The
       player's minutes across the window are divided by the TEAM's
       minutes across the same games, once. A mean of per-game shares
       would let a blowout in which the starters sat drag the average.

    2. THE CURRENT GAME'S SHARE IS NOT COMPUTABLE, and that is correct
       rather than a limitation. It would need the sibling rows of the
       game being predicted -- tonight's minutes distribution -- so any
       step producing it would publish a window end equal to its own
       tip-off, and the guard would reject it. The whole point of a role
       feature is to stand in for the minutes nobody has yet;
       MODELING_FINDINGS.md is explicit that forward-looking minutes are
       the input this repo does not have.

    Team totals are built in a first pass over the frame. That pass reads
    every row including future ones, which is safe because it only ever
    produces per-(team, game) totals and a total is attached to a
    player's history only once that game is in their past.
    """

    value_column: str
    window: int
    group_by: tuple[str, ...] = ("player_id",)
    pool_by: tuple[str, ...] = ("team_id",)
    game_key: str = "game_id"
    label: str = "role_share"

    def __post_init__(self) -> None:
        if self.window < 1:
            raise StepContractError(f"share window must be >= 1, got {self.window}")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return (f"{self.value_column}_share_{self.window}",)

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
            frame, (*self.group_by, *self.pool_by, self.game_key, self.value_column)
        )
        pool_totals: dict[tuple[object, ...], float] = {}
        for _, row in chronological(frame, self.name):
            value = row.get(self.value_column)
            if value is None:
                continue
            key = (*(row.get(c) for c in self.pool_by), row.get(self.game_key))
            pool_totals[key] = pool_totals.get(key, 0.0) + float(value)  # type: ignore[arg-type]

        def observe(row: Row) -> dict[str, object]:
            key = (*(row.get(c) for c in self.pool_by), row.get(self.game_key))
            return {"value": row.get(self.value_column), "pool": pool_totals.get(key)}

        output = self.output_columns[0]
        cells: list[Row | None] = [None] * len(frame.rows)
        for index, _row, past in trailing_walk(
            frame, self.name, group_by=self.group_by, observe=observe
        ):
            contributing = past[-self.window :]
            mine, pool, used = _paired(contributing, "value", "pool")
            cells[index] = {
                output: (mine / pool) if pool else None,
                f"{self.label}{WINDOW_COUNT_SUFFIX}": used,
                f"{self.label}{WINDOW_END_SUFFIX}": max(
                    (at for at, _ in contributing), default=None
                ),
            }
        return finalise(cells, self.name)


def team_minutes_played(frame: FeatureFrame, game_key: str = "game_id") -> dict[
    tuple[object, object], float
]:
    """(team_id, game_id) -> total minutes, for diagnostics.

    Not used by any step -- `RollingShareStep` builds its own totals
    inline. Exposed because "does this frame's minutes column add up to
    ~200 per team-game" is the one-line sanity check that catches a
    box-score source filter having gone missing, and it should not need a
    private import to run.
    """
    totals: dict[tuple[object, object], float] = {}
    for row in frame.rows:
        minutes = row.get("minutes")
        if minutes is None:
            continue
        key = (row.get("team_id"), row.get(game_key))
        totals[key] = totals.get(key, 0.0) + float(minutes)  # type: ignore[arg-type]
    return totals


__all__ = [
    "PER_36",
    "RollingRateStep",
    "RollingShareStep",
    "RollingWeightedMeanStep",
    "team_minutes_played",
]
