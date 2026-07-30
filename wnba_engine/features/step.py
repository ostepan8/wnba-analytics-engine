"""The step Protocol, plus one base class per StepKind.

`PreprocessingStep` is the whole extension point: anything with a name, a
provenance, and an `apply` is composable into a Pipeline. Concrete steps
are frozen dataclasses holding their config, so a strategy is a value --
comparable, printable, and safe to share between threads or backtest
folds.

The base classes below are not convenience wrappers. Each one implements
`apply` FINAL-ly and exposes a narrower abstract hook, and that narrowing
is the enforcement:

- RowMapStep hands the subclass exactly one row. It cannot consult another
  game even if it wants to, so "this feature is row-local" is guaranteed
  by the signature rather than asserted by a comment.
- WindowedStep is the only base class that sees the whole frame, and it
  forces the resulting window-end column into the frame's declarations on
  the subclass's behalf -- a windowed step cannot forget to publish where
  its window stopped.
- FilterStep can only answer keep/drop, so it cannot invent a row.

Subclasses implement `name` and `provenance` as properties rather than
receiving them as fields: for the configurable steps (rolling windows,
scalers) the declared column names are DERIVED from config, and a field
would let the two drift.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepProvenance


@runtime_checkable
class PreprocessingStep(Protocol):
    """One swappable preprocessing operation."""

    @property
    def name(self) -> str:
        """Unique within a Pipeline -- it is the handle `without()` and
        `replace_step()` address, so duplicates are rejected there.
        """

    @property
    def provenance(self) -> StepProvenance:
        """What this step promises about the data it produces."""

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        """Return a NEW frame. Never mutates `frame`."""


class FeatureStep(ABC):
    """Shared plumbing for the concrete bases below."""

    __slots__ = ()

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def provenance(self) -> StepProvenance: ...

    @abstractmethod
    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame: ...

    def _require_columns(self, frame: FeatureFrame, needed: Iterable[str]) -> None:
        """Fail fast on a missing input column.

        Without this a step reading a column that an earlier step was
        meant to produce sees None everywhere and emits a whole column of
        nulls -- which downstream looks like sparse data rather than a
        mis-ordered pipeline.
        """
        missing = [c for c in needed if c not in frame.column_set]
        if missing:
            raise StepContractError(
                f"step {self.name!r} needs columns {missing} which are not in the frame; "
                f"available: {list(frame.columns)}"
            )


class SourceStep(FeatureStep):
    """Creates the frame's rows from outside the frame.

    Must run first: a second SOURCE step would either replace rows another
    step already produced (silently discarding work) or concatenate frames
    with different schemas. Enriching existing rows from another table is
    what AsOfJoinStep is for.
    """

    __slots__ = ()

    @abstractmethod
    def fetch(self, context: FeatureContext) -> tuple[Row, ...]:
        """Rows for this context. MUST already be filtered by
        `context.as_of` -- the guard is a backstop that catches mistakes,
        not the mechanism that makes loading safe.
        """

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        if frame.columns or frame.rows:
            raise StepContractError(
                f"source step {self.name!r} must run on an empty frame; it received "
                f"{len(frame)} row(s) with columns {list(frame.columns)}. Use a "
                "AsOfJoinStep to enrich rows that already exist."
            )
        provenance = self.provenance
        return FeatureFrame.from_rows(
            self.fetch(context),
            columns=provenance.adds_columns,
            as_of_columns=provenance.as_of_columns,
            event_time_column=provenance.event_time_column,
        )


class AsOfJoinStep(FeatureStep):
    """Enriches existing rows with the newest observation BEFORE each row.

    The naive version of this class -- "fetch the latest snapshot at or
    before context.as_of, join it onto every row" -- is a leak, and it is
    one this codebase actually produced before the guard grew teeth: a
    build with as_of=2026-07-29 handed a game played on 2026-05-10 the
    standings captured on 2026-07-14, i.e. that team's record AFTER two
    further months of results. Every row passed the as-of check, because
    2026-07-14 really is before the boundary.

    So a join here is per-row as-of, not per-frame: each row gets the most
    recent observation strictly before its OWN event time. The joined
    timestamp is registered as a window end as well as an as-of anchor, so
    the guard enforces that ordering instead of taking the implementation's
    word for it.

    Left-join semantics: no qualifying observation means None for every
    added column. That is the honest answer, and it is common --
    team_standings_history starts at 2026-07-09, so every earlier game
    legitimately gets nulls.
    """

    __slots__ = ()

    @abstractmethod
    def observations(
        self, context: FeatureContext
    ) -> Mapping[tuple[object, ...], Sequence[tuple[datetime, Row]]]:
        """Join key -> (observed_at, cells), any order. Fetched once."""

    @abstractmethod
    def key_for(self, row: Row) -> tuple[object, ...]:
        """This row's join key."""

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        if frame.event_time_column is None:
            raise StepContractError(
                f"as-of join {self.name!r} needs an event-time column to join against"
            )
        provenance = self.provenance
        observed = {
            key: sorted(entries, key=lambda entry: entry[0])
            for key, entries in self.observations(context).items()
        }
        absent: Row = dict.fromkeys(provenance.adds_columns)
        cells = tuple(
            self._latest_before(observed.get(self.key_for(row), ()), row, frame) or absent
            for row in frame.rows
        )
        merged = frame.merge_cells(cells, provenance.adds_columns)
        return merged.declaring(
            as_of_columns=provenance.as_of_columns,
            window_end_columns=provenance.as_of_columns,
        )

    def _latest_before(
        self, entries: Sequence[tuple[datetime, Row]], row: Row, frame: FeatureFrame
    ) -> Row | None:
        event_time = row.get(frame.event_time_column or "")
        if not isinstance(event_time, datetime):
            raise StepContractError(
                f"as-of join {self.name!r} needs a datetime event time, got "
                f"{type(event_time).__name__}"
            )
        chosen: Row | None = None
        for observed_at, cells in entries:  # ascending
            if observed_at >= event_time:
                break
            chosen = cells
        return chosen


class TimeInvariantJoinStep(FeatureStep):
    """A join for data with no as-of anchor because it genuinely has none.

    Height, weight, and college do not change; DATA_INVENTORY.md calls
    them "effectively permanent" against `age`/`jersey_number`, which it
    calls mutable snapshot values "refreshed on every re-ingestion".
    There is no captured_at on `players` to prove when any of it was
    observed, so the honest classification is time-invariant WITH a
    written justification -- not a fabricated anchor.
    """

    __slots__ = ()

    @abstractmethod
    def lookup(self, context: FeatureContext) -> Mapping[tuple[object, ...], Row]:
        """Join key -> cells to merge."""

    @abstractmethod
    def key_for(self, row: Row) -> tuple[object, ...]:
        """This row's join key."""

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        provenance = self.provenance
        table = self.lookup(context)
        absent: Row = dict.fromkeys(provenance.adds_columns)
        cells = tuple(table.get(self.key_for(row), absent) for row in frame.rows)
        return frame.merge_cells(cells, provenance.adds_columns)


class RowMapStep(FeatureStep):
    """Adds columns computed from ONE row.

    The signature is the point: `transform` receives a single row and has
    no route to any other, so no row-local step can accidentally become a
    cross-row aggregate.
    """

    __slots__ = ()

    @abstractmethod
    def transform(self, row: Row, context: FeatureContext) -> Row:
        """Only the NEW cells -- they are merged over the row."""

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        cells = tuple(self.transform(row, context) for row in frame.rows)
        return frame.merge_cells(cells, self.provenance.adds_columns)


class WindowedStep(FeatureStep):
    """Adds columns computed from OTHER rows in the frame.

    The only base class with whole-frame visibility, and therefore the
    only one that can leak within an otherwise-valid frame. The tax for
    that visibility is the window-end column, which `apply` forces into
    the frame's declarations so the guard checks it whether or not the
    subclass author remembered it exists.
    """

    __slots__ = ()

    @abstractmethod
    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        """Per-row cells, positionally aligned to `frame.rows`."""

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        if frame.event_time_column is None:
            raise StepContractError(
                f"windowed step {self.name!r} needs an event-time column to check its "
                "window against; the frame declares none"
            )
        provenance = self.provenance
        window_end = provenance.window_end_column
        assert window_end is not None  # guaranteed by StepProvenance.__post_init__
        merged = frame.merge_cells(self.compute(frame, context), provenance.adds_columns)
        # Registered as BOTH: window-end so it is checked against the row's
        # own event time, and as-of so a window that somehow reached past
        # the global boundary fails too.
        return merged.declaring(
            as_of_columns=(window_end,), window_end_columns=(window_end,)
        )


class FilterStep(FeatureStep):
    """Drops rows. Cannot add columns, cannot add rows."""

    __slots__ = ()

    @abstractmethod
    def keep(self, row: Row, context: FeatureContext) -> bool: ...

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        return frame.filter_rows(lambda row: self.keep(row, context))


class FittedStep(FeatureStep):
    """Derives parameters from the frame, then applies them row-wise.

    Safe with respect to TIME, not with respect to the cross-section: the
    frame it fits on has already passed the guard, so no parameter can be
    influenced by anything after `as_of`. It CAN be influenced by other
    rows inside the window -- a z-score's mean includes the row being
    scaled. That is standard practice and is called out in the README's
    "what the guard does not catch"; where it matters, use the explicitly
    parameterised variant instead (see steps/encoding.py).
    """

    __slots__ = ()

    @abstractmethod
    def fit(self, frame: FeatureFrame, context: FeatureContext) -> Sequence[object]:
        """Parameters, opaque to this base class."""

    @abstractmethod
    def transform_fitted(
        self, row: Row, params: Sequence[object], context: FeatureContext
    ) -> Row: ...

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        params = self.fit(frame, context)
        cells = tuple(self.transform_fitted(row, params, context) for row in frame.rows)
        return frame.merge_cells(cells, self.provenance.adds_columns)
