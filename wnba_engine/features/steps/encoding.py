"""Categorical encoding and numeric scaling.

The rule that shapes this whole module: an encoder must never see data
from outside the context window. There are two ways to honour it, and
both are offered because they fail differently.

**Explicit parameters** (`OneHotStep`, `ScaleStep`) take their categories
or their mean/stddev as config. They are ROW_LOCAL, so they cannot see
any other row at all, and they are reproducible: the same step applied at
a later boundary produces the same encoding, which is what a backtest
comparing two folds actually needs.

**Fitted** (`FitScaleStep`) derives parameters from the frame at apply
time. Safe with respect to TIME -- the frame it fits on has already
passed the guard, so no observation after `as_of` can influence a
parameter -- but NOT with respect to the cross-section: a z-score's mean
includes the row being scaled, and a walk-forward backtest gets a
slightly different mean per fold. That is normal practice and normally
harmless; it is still a real caveat and is repeated in the README's "what
the guard does not catch".

There is deliberately **no fitted one-hot encoder.** Discovering
categories from data makes the output SCHEMA data-dependent, which
defeats the guard's "a step adds exactly the columns it declared" check
and would mean two boundaries produce frames with different columns. Fit
the categories yourself with `observed_categories()` and pass them in --
one extra line, and the encoding becomes a reviewable constant.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import FittedStep, RowMapStep

ONE_HOT_SEPARATOR = "_is_"
SCALED_SUFFIX = "_scaled"


def observed_categories(frame: FeatureFrame, column: str) -> tuple[str, ...]:
    """Sorted distinct non-null values -- the input to OneHotStep.

    A helper, not a step, on purpose: calling it puts the discovered
    categories in front of a human before they are baked into a strategy.
    """
    values = {row.get(column) for row in frame.rows if row.get(column) is not None}
    return tuple(sorted(str(value) for value in values))


@dataclass(frozen=True, slots=True)
class OneHotStep(RowMapStep):
    """One boolean column per declared category.

    Unknown values encode as all-False rather than raising. A category
    that appears only after the boundary the categories were chosen at is
    a real and expected event (a 2026 expansion franchise, a new
    season_type), and failing the whole build on it would make the
    encoder unusable in exactly the walk-forward setting it exists for.
    `<column>_is_other` records that it happened, so "all zeros" is never
    ambiguous between "unknown category" and "value was null".
    """

    column: str
    categories: tuple[str, ...]
    step_name: str = ""

    def __post_init__(self) -> None:
        if not self.categories:
            raise StepContractError(f"one-hot of {self.column!r} needs at least one category")
        duplicates = len(self.categories) != len(set(self.categories))
        if duplicates:
            raise StepContractError(f"one-hot categories for {self.column!r} contain duplicates")

    @property
    def name(self) -> str:
        return self.step_name or f"one_hot_{self.column}"

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(
            f"{self.column}{ONE_HOT_SEPARATOR}{category}" for category in self.categories
        ) + (f"{self.column}{ONE_HOT_SEPARATOR}other",)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        value = row.get(self.column)
        text = None if value is None else str(value)
        cells: dict[str, object] = {
            f"{self.column}{ONE_HOT_SEPARATOR}{category}": text == category
            for category in self.categories
        }
        cells[f"{self.column}{ONE_HOT_SEPARATOR}other"] = (
            text is not None and text not in self.categories
        )
        return cells


@dataclass(frozen=True, slots=True)
class ScaleStep(RowMapStep):
    """(value - mean) / stddev with parameters supplied as config.

    Nulls stay null. Imputing a scaled zero would put the row exactly at
    the mean, which is a strong and invented claim about a value we do
    not have -- pair with FillNullsStep/FlagNullsStep if a numeric zero
    is genuinely wanted.
    """

    column: str
    mean: float
    stddev: float
    step_name: str = ""

    def __post_init__(self) -> None:
        if self.stddev <= 0:
            raise StepContractError(
                f"scale of {self.column!r} needs a positive stddev, got {self.stddev}"
            )

    @property
    def name(self) -> str:
        return self.step_name or f"scale_{self.column}"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.ROW_LOCAL, adds_columns=(f"{self.column}{SCALED_SUFFIX}",)
        )

    def transform(self, row: Row, context: FeatureContext) -> Row:
        value = row.get(self.column)
        if value is None:
            return {f"{self.column}{SCALED_SUFFIX}": None}
        return {f"{self.column}{SCALED_SUFFIX}": (float(value) - self.mean) / self.stddev}  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class FitScaleStep(FittedStep):
    """Standardise using parameters fitted on THIS frame.

    Time-safe, cross-section-leaky -- see the module docstring. A frame
    whose column is constant or entirely null scales to 0.0 rather than
    dividing by zero; that is the correct answer (a constant carries no
    information) and keeps a degenerate early-season slice from aborting
    a whole build.
    """

    column: str
    step_name: str = ""

    @property
    def name(self) -> str:
        return self.step_name or f"fit_scale_{self.column}"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.FITTED, adds_columns=(f"{self.column}{SCALED_SUFFIX}",)
        )

    def fit(self, frame: FeatureFrame, context: FeatureContext) -> Sequence[object]:
        self._require_columns(frame, (self.column,))
        values = [
            float(row[self.column])  # type: ignore[arg-type]
            for row in frame.rows
            if row.get(self.column) is not None
        ]
        if not values:
            return (0.0, 0.0)
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return (mean, sqrt(variance))

    def transform_fitted(
        self, row: Row, params: Sequence[object], context: FeatureContext
    ) -> Row:
        mean, stddev = float(params[0]), float(params[1])  # type: ignore[arg-type]
        value = row.get(self.column)
        if value is None:
            return {f"{self.column}{SCALED_SUFFIX}": None}
        if stddev == 0.0:
            return {f"{self.column}{SCALED_SUFFIX}": 0.0}
        return {f"{self.column}{SCALED_SUFFIX}": (float(value) - mean) / stddev}  # type: ignore[arg-type]
