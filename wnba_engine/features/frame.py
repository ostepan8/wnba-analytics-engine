"""The interchange type every step consumes and produces.

Deliberately NOT pandas. Three reasons, in order of weight:

1. This repo's dependency list is httpx/psycopg/click/tenacity/dotenv and
   nothing else, and ROADMAP.md puts ML behind an explicit later decision.
   Pulling in a ~60 MB numerical stack to shape 2,700 team-game rows would
   spend that decision early and by accident.
2. The frames are small. The whole database is 1,369 games (~2,700
   team-game rows) and ~31k single-source player-game rows; a tuple of
   dicts costs milliseconds.
3. Typed rows make the leakage guard possible. The guard has to inspect
   per-row source timestamps and compare them to a boundary; with dicts
   that is a loop, with a DataFrame it is dtype archaeology (pandas
   silently coerces mixed tz-aware datetimes to object, and None to NaN,
   either of which would turn a leak into a comparison that quietly
   returns False).

`to_columns()` is the escape hatch: `pd.DataFrame(frame.to_columns())` or
`pl.DataFrame(frame.to_columns())` is a one-liner whenever that decision
is actually made.

Every method returns a NEW frame. Rows are wrapped in MappingProxyType by
`from_rows`, so "immutable" is enforced by the runtime rather than by
convention -- a step that tries to write back into a row it was handed
gets a TypeError instead of quietly corrupting a shared row for every
downstream step.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from wnba_engine.features.errors import StepContractError

Row = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    """Rows plus the provenance declarations the guard checks them against.

    The three declaration fields are what separate this from a bare list
    of dicts, and each one answers a question the guard must be able to
    ask WITHOUT knowing which step produced the frame:

    - `as_of_columns`: which columns hold a source timestamp that must be
      <= context.as_of. A frame with rows and no as_of column is rejected
      outright (see LeakageGuard) -- unprovable is not the same as safe.
    - `event_time_column`: the row's OWN event instant (games.start_time).
      Backward-looking features are checked against this, not against
      as_of: a rolling window ending after the target game's tip-off is a
      leak even when the whole frame sits comfortably before as_of.
    - `window_end_columns`: the last instant each backward-looking feature
      actually consumed. Making a windowed step publish this turns "the
      window is backward-looking" from a code-review claim into a
      per-row assertion.
    """

    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    as_of_columns: frozenset[str] = frozenset()
    window_end_columns: frozenset[str] = frozenset()
    event_time_column: str | None = None

    @classmethod
    def empty(cls) -> FeatureFrame:
        """The starting frame every Pipeline folds over."""
        return cls(columns=(), rows=())

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Row],
        *,
        columns: tuple[str, ...],
        as_of_columns: Iterable[str] = (),
        window_end_columns: Iterable[str] = (),
        event_time_column: str | None = None,
    ) -> FeatureFrame:
        """Build a frame, freezing each row against later mutation.

        `columns` is explicit rather than inferred from the first row on
        purpose: a source that omits a null column on some rows would
        otherwise produce a frame whose schema depends on which row came
        back first, and the guard's "a step may add only what it declared"
        check would start passing or failing based on row order.
        """
        frozen = tuple(MappingProxyType(dict(row)) for row in rows)
        return cls(
            columns=tuple(columns),
            rows=frozen,
            as_of_columns=frozenset(as_of_columns),
            window_end_columns=frozenset(window_end_columns),
            event_time_column=event_time_column,
        )

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def column_set(self) -> frozenset[str]:
        return frozenset(self.columns)

    def declaring(
        self,
        *,
        as_of_columns: Iterable[str] = (),
        window_end_columns: Iterable[str] = (),
        event_time_column: str | None = None,
    ) -> FeatureFrame:
        """A copy with declarations ADDED (never removed).

        Additive on purpose: a step that could clear another step's as-of
        anchor would be able to launder leaky data by dropping the
        declaration that exposes it. Dropping an anchor requires `select`,
        which refuses (see below).
        """
        return replace(
            self,
            as_of_columns=self.as_of_columns | frozenset(as_of_columns),
            window_end_columns=self.window_end_columns | frozenset(window_end_columns),
            event_time_column=event_time_column or self.event_time_column,
        )

    def with_rows(self, rows: Iterable[Row]) -> FeatureFrame:
        """Same schema and declarations, different rows (filters, sorts)."""
        return replace(self, rows=tuple(MappingProxyType(dict(row)) for row in rows))

    def with_column(self, name: str, values: Sequence[object]) -> FeatureFrame:
        """One new column, aligned positionally to `rows`."""
        return self.merge_cells(tuple({name: value} for value in values), (name,))

    def merge_cells(
        self, cells: Sequence[Row], added_columns: Sequence[str]
    ) -> FeatureFrame:
        """Merge per-row cell maps in, returning a new frame.

        The workhorse behind every column-adding step. `added_columns` is
        passed separately rather than derived from `cells` because a step
        must declare its schema even for rows where the value happens to
        be None -- otherwise a feature that is null for the first N rows
        would appear to change the frame's schema partway through.
        """
        if len(cells) != len(self.rows):
            raise StepContractError(
                f"cell count {len(cells)} does not match row count {len(self.rows)}"
            )
        merged = tuple(
            MappingProxyType({**row, **cell}) for row, cell in zip(self.rows, cells, strict=True)
        )
        new_columns = tuple(c for c in added_columns if c not in self.column_set)
        return replace(self, columns=self.columns + new_columns, rows=merged)

    def filter_rows(self, predicate: Callable[[Row], bool]) -> FeatureFrame:
        return replace(self, rows=tuple(row for row in self.rows if predicate(row)))

    def select(self, names: Sequence[str]) -> FeatureFrame:
        """Project to `names`, refusing to drop a declared anchor.

        Projection is the one operation that could quietly disarm the
        guard: drop `start_time` and every window-end check becomes
        unevaluatable, drop the as-of columns and the frame looks like it
        was never sourced from anywhere. Both are rejected rather than
        silently downgraded.
        """
        keep = frozenset(names)
        missing = keep - self.column_set
        if missing:
            raise StepContractError(f"select of unknown columns: {sorted(missing)}")
        dropped_anchors = (self.as_of_columns | self.window_end_columns) - keep
        if dropped_anchors:
            raise StepContractError(
                f"select would drop declared as-of/window anchors {sorted(dropped_anchors)}; "
                "the leakage guard cannot verify a frame that hides its own provenance"
            )
        if self.event_time_column is not None and self.event_time_column not in keep:
            raise StepContractError(
                f"select would drop the event-time column {self.event_time_column!r}"
            )
        return replace(
            self,
            columns=tuple(c for c in self.columns if c in keep),
            rows=tuple(
                MappingProxyType({k: v for k, v in row.items() if k in keep}) for row in self.rows
            ),
        )

    def to_columns(self) -> dict[str, list[object]]:
        """Columnar export -- the one-line bridge to pandas/polars/numpy
        if and when ROADMAP.md's ML decision is actually made.
        """
        return {name: [row.get(name) for row in self.rows] for name in self.columns}

    def head(self, count: int = 5) -> tuple[Row, ...]:
        return self.rows[:count]
