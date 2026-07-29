"""Null policy, type coercion, and duplicate handling.

Null policy is per-column and explicit -- there is no frame-wide
`dropna()` here on purpose. In this dataset a null means several
genuinely different things and a blanket policy destroys the distinction:

- `pace` is null for any game with no balldontlie advanced-stats row.
  Dropping those rows silently restricts the frame to games one paid
  provider happened to cover.
- `minutes`/`points` are null for a DNP (see
  db/migrations/0002_box_scores.sql: "Stat columns are NULL for players
  who did not play"). Filling those with 0 is defensible for a totals
  model and outright wrong for a per-minute rate.
- `standings_*` is null when no snapshot existed at the boundary, which
  is information, not absence.

So the caller states, per column, which of drop / fill / flag applies,
and gets a step that does exactly that.

Type coercion earns its own step because psycopg maps NUMERIC to
decimal.Decimal. Decimal will not mix with float in arithmetic
(`Decimal('98.5') * 0.5` raises TypeError), so an unconverted pace column
turns the first rolling average into a crash -- or, worse, into a
silently-Decimal column whose later `float()` cast rounds differently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import FilterStep, RowMapStep

NULL_FLAG_SUFFIX = "_is_null"


@dataclass(frozen=True, slots=True)
class FillPolicy:
    """Replace nulls in `column` with `value`."""

    column: str
    value: object


@dataclass(frozen=True, slots=True)
class FillNullsStep(RowMapStep):
    """Apply per-column fill values in place (no new columns).

    Row-local by construction, so a fill value can never be derived from
    other rows -- an imputation that used the column mean would be a
    FittedStep, and would have to say so.
    """

    policies: tuple[FillPolicy, ...]
    step_name: str = "fill_nulls"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        # Overwrites existing columns rather than adding any.
        return StepProvenance(kind=StepKind.ROW_LOCAL)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        return {
            policy.column: policy.value
            for policy in self.policies
            if row.get(policy.column) is None
        }


@dataclass(frozen=True, slots=True)
class FlagNullsStep(RowMapStep):
    """Add `<column>_is_null` booleans, leaving the values alone.

    Pairs with FillNullsStep: fill so downstream arithmetic works, flag so
    the model can still tell an imputed zero from a real one. Flag BEFORE
    filling, or every flag reads False.
    """

    columns: tuple[str, ...]
    step_name: str = "flag_nulls"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.ROW_LOCAL,
            adds_columns=tuple(f"{c}{NULL_FLAG_SUFFIX}" for c in self.columns),
        )

    def transform(self, row: Row, context: FeatureContext) -> Row:
        return {f"{c}{NULL_FLAG_SUFFIX}": row.get(c) is None for c in self.columns}


@dataclass(frozen=True, slots=True)
class DropNullRowsStep(FilterStep):
    """Drop rows where any of `columns` is null.

    A FILTER, not a cleaning transform, because it changes the row count
    -- and the guard holds filters to a different contract than column
    steps precisely so this cannot happen by accident inside a "cleaning"
    step that claims to only touch values.
    """

    columns: tuple[str, ...]
    step_name: str = "drop_null_rows"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        return all(row.get(column) is not None for column in self.columns)


def _to_float(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    raise StepContractError(f"cannot coerce {type(value).__name__} {value!r} to float")


def _to_int(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    raise StepContractError(f"cannot coerce {type(value).__name__} {value!r} to int")


def _to_bool(value: object) -> object:
    return None if value is None else bool(value)


#: Named rather than exposing raw callables so a strategy reads as
#: `("pace", TO_FLOAT)` and a typo is an ImportError.
TO_FLOAT: Callable[[object], object] = _to_float
TO_INT: Callable[[object], object] = _to_int
TO_BOOL: Callable[[object], object] = _to_bool


@dataclass(frozen=True, slots=True)
class CoerceTypesStep(RowMapStep):
    """Coerce columns to a Python type, null-preserving.

    Nulls pass through untouched: coercing them would erase the
    distinction FillNullsStep and FlagNullsStep exist to preserve.
    """

    coercions: tuple[tuple[str, Callable[[object], object]], ...]
    step_name: str = "coerce_types"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        return {column: coerce(row.get(column)) for column, coerce in self.coercions}


@dataclass(frozen=True, slots=True)
class DeduplicateStep(FilterStep):
    """Keep the FIRST row per key, drop later ones.

    "First" is meaningful because every loader orders by start_time, so
    the survivor is the earliest observation rather than an arbitrary one.

    This is a safety net, not a fix: the real duplicate risk in this
    database is forgetting to filter `player_game_stats.source`, which
    produces two rows per (player, game) that are NOT duplicates -- they
    are two providers' independent observations, and silently keeping one
    would hide the query bug. Deduplicating on (player_id, game_id) here
    would mask exactly that, so strategies filter by source at the query
    instead and use this only where a genuine repeat is possible.
    """

    key_columns: tuple[str, ...]
    step_name: str = "deduplicate"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:  # pragma: no cover
        raise StepContractError(
            "DeduplicateStep needs cross-row state; it overrides apply() instead"
        )

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        self._require_columns(frame, self.key_columns)
        seen: set[tuple[object, ...]] = set()
        kept: list[Row] = []
        for row in frame.rows:
            key = tuple(row.get(column) for column in self.key_columns)
            if key in seen:
                continue
            seen.add(key)
            kept.append(row)
        return frame.with_rows(kept)


def fill_policies(pairs: Mapping[str, object] | Sequence[tuple[str, object]]) -> tuple[
    FillPolicy, ...
]:
    """Convenience builder so a strategy can write a dict literal."""
    items = pairs.items() if isinstance(pairs, Mapping) else pairs
    return tuple(FillPolicy(column=column, value=value) for column, value in items)
