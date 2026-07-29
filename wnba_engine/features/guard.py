"""The leakage guard: run after EVERY step, not once at the end.

Running per step is the whole point. A single end-of-pipeline check tells
you the output is contaminated; a per-step check tells you which step did
it, which is the difference between a five-minute fix and an afternoon of
bisecting a strategy.

Four families of check, in the order they run:

1. STRUCTURAL -- did the step do only what its StepKind permits (rows,
   columns)? These run first because the leakage checks below are only
   meaningful on a frame whose shape is accounted for. A step that can
   silently add a column can silently add a leaky one.
2. PROVENANCE -- can this frame prove where its rows came from at all? A
   frame with rows and no as-of anchor is rejected. Unprovable is treated
   as unsafe, because the cheapest way to defeat a timestamp check is to
   emit no timestamp.
3. BOUNDARY -- is every source timestamp <= context.as_of? This is the
   check that catches the traps DATA_INVENTORY.md documents: a standings
   snapshot captured after the boundary, odds captured after tip-off.
4. WINDOW -- is every backward-looking feature's window end strictly
   BEFORE the row's own event time? This is the one a naive
   as_of-only guard misses entirely: a rolling average that includes the
   game it is predicting sits comfortably inside the global boundary and
   is still a leak.

The guard is a value (frozen, no state), so it can be swapped or
tightened per Pipeline without any of the checks becoming optional by
accident -- Pipeline holds one and always runs it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import (
    LeakageError,
    StepContractError,
    UndeclaredProvenanceError,
)
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind

#: Kinds that must leave the row count exactly as they found it. SOURCE
#: creates rows; FILTER removes them; everything else is a column
#: operation and a change in row count means it did something else.
_ROW_COUNT_PRESERVING = frozenset(
    {
        StepKind.JOIN,
        StepKind.TIME_INVARIANT,
        StepKind.ROW_LOCAL,
        StepKind.WINDOWED,
        StepKind.FITTED,
    }
)


@dataclass(frozen=True, slots=True)
class LeakageGuard:
    """Point-in-time enforcement for one step's output.

    `sample_limit` bounds nothing about correctness -- every row is
    checked. It exists only so the error message from a broken step on a
    60k-row frame stays readable.
    """

    sample_limit: int = 3

    def check(
        self,
        *,
        step_name: str,
        kind: StepKind,
        declared_columns: Sequence[str],
        before: FeatureFrame,
        after: FeatureFrame,
        context: FeatureContext,
    ) -> None:
        self._check_structure(step_name, kind, declared_columns, before, after)
        self._check_provenance_declared(step_name, after)
        self._check_as_of_boundary(step_name, after, context)
        self._check_window_ends(step_name, after)

    # -- 1. structural -------------------------------------------------

    def _check_structure(
        self,
        step_name: str,
        kind: StepKind,
        declared_columns: Sequence[str],
        before: FeatureFrame,
        after: FeatureFrame,
    ) -> None:
        added = after.column_set - before.column_set
        declared = frozenset(declared_columns)
        if added != declared:
            raise StepContractError(
                f"step {step_name!r} declared columns {sorted(declared)} but added "
                f"{sorted(added)}. A step's declaration is what the guard checks "
                "against; drift between the two is how an unreviewed feature gets in."
            )
        removed = before.column_set - after.column_set
        if removed:
            raise StepContractError(
                f"step {step_name!r} removed columns {sorted(removed)}; use "
                "FeatureFrame.select explicitly if a projection is intended"
            )
        if kind in _ROW_COUNT_PRESERVING and len(after) != len(before):
            raise StepContractError(
                f"{kind} step {step_name!r} changed the row count "
                f"({len(before)} -> {len(after)}); only SOURCE may add rows and only "
                "FILTER may drop them"
            )
        if kind is StepKind.FILTER and len(after) > len(before):
            raise StepContractError(
                f"filter step {step_name!r} increased the row count "
                f"({len(before)} -> {len(after)}); a filter that invents rows is "
                "inventing observations"
            )

    # -- 2. provenance -------------------------------------------------

    def _check_provenance_declared(self, step_name: str, after: FeatureFrame) -> None:
        if not after.rows:
            return  # an empty frame carries no observations to leak
        if not after.as_of_columns:
            raise UndeclaredProvenanceError(
                f"after step {step_name!r} the frame holds {len(after)} row(s) but "
                "declares no as-of column. A frame that cannot say when its data "
                "was observable cannot be shown to be point-in-time correct, so it "
                "is rejected rather than assumed safe."
            )
        missing = after.as_of_columns - after.column_set
        if missing:
            raise UndeclaredProvenanceError(
                f"after step {step_name!r} the frame declares as-of columns "
                f"{sorted(missing)} that it does not contain"
            )
        if after.event_time_column is None:
            raise UndeclaredProvenanceError(
                f"after step {step_name!r} the frame has rows but no event-time "
                "column; per-row window checks would be unevaluatable"
            )

    # -- 3. boundary ---------------------------------------------------

    def _check_as_of_boundary(
        self, step_name: str, after: FeatureFrame, context: FeatureContext
    ) -> None:
        anchors = tuple(sorted(after.as_of_columns))
        for row in after.rows:
            observed_any = False
            for column in anchors:
                value = row.get(column)
                if value is None:
                    # A null anchor means "no observation existed at this
                    # boundary" -- the correct left-join answer, and not
                    # something that can leak. It is only tolerated because
                    # the check below still demands at least one real
                    # anchor per row.
                    continue
                timestamp = _as_datetime(step_name, column, value)
                observed_any = True
                if timestamp > context.as_of:
                    raise LeakageError(
                        step=step_name,
                        column=column,
                        observed=timestamp,
                        boundary=context.as_of,
                        detail="as-of",
                    )
            if not observed_any:
                raise UndeclaredProvenanceError(
                    f"after step {step_name!r} a row has no non-null as-of anchor "
                    f"among {list(anchors)}: {_sample(row, self.sample_limit)}"
                )

    # -- 4. windows ----------------------------------------------------

    def _check_window_ends(self, step_name: str, after: FeatureFrame) -> None:
        if not after.window_end_columns:
            return
        event_column = after.event_time_column
        assert event_column is not None  # _check_provenance_declared ran first
        for row in after.rows:
            event_time = row.get(event_column)
            if event_time is None:
                raise UndeclaredProvenanceError(
                    f"after step {step_name!r} a row has a null event time "
                    f"({event_column}), so its backward-looking features cannot be "
                    "verified"
                )
            event_at = _as_datetime(step_name, event_column, event_time)
            for column in sorted(after.window_end_columns):
                window_end = row.get(column)
                if window_end is None:
                    continue  # no prior observation -- an empty window leaks nothing
                ended_at = _as_datetime(step_name, column, window_end)
                if ended_at >= event_at:
                    raise LeakageError(
                        step=step_name,
                        column=column,
                        observed=ended_at,
                        boundary=event_at,
                        detail="row's own event-time",
                    )


def _as_datetime(step_name: str, column: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise StepContractError(
            f"step {step_name!r} declared {column!r} as a timestamp anchor but the "
            f"value is {type(value).__name__}: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        # A naive timestamp compares as though it were in whatever zone
        # the reader assumes, which is exactly how an "it passed locally"
        # leak happens. Every timestamp in this database is TIMESTAMPTZ,
        # so a naive one means somebody stripped the zone en route.
        raise StepContractError(
            f"step {step_name!r} produced a naive datetime in anchor column "
            f"{column!r}; anchors must stay timezone-aware to be comparable"
        )
    return value


def _sample(row: Row, limit: int) -> str:
    items = list(row.items())[:limit]
    return "{" + ", ".join(f"{k}={v!r}" for k, v in items) + ", ...}"


#: The guard every Pipeline gets unless one is passed explicitly. A module
#: constant rather than a default-constructed field so "which guard ran?"
#: has one answer across the codebase.
DEFAULT_GUARD = LeakageGuard()
