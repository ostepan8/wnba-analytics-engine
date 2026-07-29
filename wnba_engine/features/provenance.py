"""What a step must declare about itself before it is allowed to run.

The design premise: leakage is not caught by reviewing code, it is caught
by making the unsafe shape impossible to express. A step therefore does
not get to say "trust me" -- it classifies itself into one of a small set
of kinds, each of which carries a structural obligation the guard can
check mechanically:

| kind           | rows            | as-of anchor                        |
|----------------|-----------------|-------------------------------------|
| SOURCE         | creates them    | REQUIRED, plus an event-time column |
| JOIN           | must not change | REQUIRED (the joined-in timestamp)  |
| TIME_INVARIANT | must not change | forbidden, `justification` REQUIRED |
| ROW_LOCAL      | must not change | forbidden (sees one row at a time)  |
| WINDOWED       | must not change | REQUIRED window-end column          |
| FILTER         | may only shrink | forbidden (adds no columns at all)  |
| FITTED         | must not change | forbidden (fits on the guarded frame) |

Two of those rows carry most of the value:

- ROW_LOCAL steps are handed ONE row and physically cannot see another,
  so "this derivation doesn't peek at other games" stops being a claim.
  Anything that genuinely needs cross-row context must be WINDOWED...
- ...and WINDOWED steps must publish the last instant their window
  consumed, which the guard asserts is strictly before the row's own
  event time. That is what makes "a season aggregate spanning the target
  game" fail instead of scoring suspiciously well.

Validation happens in __post_init__, so a mis-declared step raises at
CONSTRUCTION time. Strategies are built at import time, which means an
ill-formed step is an ImportError, not a surprise three hours into a
backfill.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StepKind(StrEnum):
    SOURCE = "source"
    JOIN = "join"
    TIME_INVARIANT = "time_invariant"
    ROW_LOCAL = "row_local"
    WINDOWED = "windowed"
    FILTER = "filter"
    FITTED = "fitted"


#: Kinds that introduce data from outside the frame and therefore must
#: name the timestamp proving when that data was observable.
_ANCHOR_REQUIRED = frozenset({StepKind.SOURCE, StepKind.JOIN})

#: Kinds that derive from what is already in the frame. They must NOT
#: name an as-of anchor, because inventing one would let a derived column
#: masquerade as independently-sourced and inherit its own approval.
_ANCHOR_FORBIDDEN = frozenset(
    {
        StepKind.TIME_INVARIANT,
        StepKind.ROW_LOCAL,
        StepKind.WINDOWED,
        StepKind.FILTER,
        StepKind.FITTED,
    }
)


@dataclass(frozen=True, slots=True)
class StepProvenance:
    """One step's self-declaration.

    `adds_columns` is checked against what the step actually produced, so
    the declaration cannot drift from the code: a loader whose SQL grows a
    column without updating this tuple fails on the next run rather than
    quietly widening the feature set.
    """

    kind: StepKind
    adds_columns: tuple[str, ...] = ()
    #: Columns holding a source timestamp that must be <= context.as_of.
    as_of_columns: tuple[str, ...] = ()
    #: SOURCE only: the column carrying each row's own event instant.
    event_time_column: str | None = None
    #: WINDOWED only: the column carrying the last instant the window used.
    window_end_column: str | None = None
    #: SOURCE/JOIN only: which tables the step reads. Documentation AND
    #: the second line of defence -- feature_repo refuses the known-leaky
    #: ones by name, this makes the intent greppable from the step side.
    source_tables: tuple[str, ...] = ()
    #: TIME_INVARIANT only: why this data has no as-of anchor and needs
    #: none. Required so "it has no timestamp" is a written argument
    #: someone signed, not an omission.
    justification: str | None = None

    def __post_init__(self) -> None:
        if self.kind in _ANCHOR_REQUIRED and not self.as_of_columns:
            raise ValueError(
                f"{self.kind} step must declare at least one as_of column -- data "
                "brought in from outside the frame has to name the timestamp that "
                "proves when it was observable"
            )
        if self.kind in _ANCHOR_FORBIDDEN and self.as_of_columns:
            raise ValueError(
                f"{self.kind} step must not declare as_of columns; it derives from "
                "the frame, which is already bounded, and a fresh anchor here would "
                "let a derived column claim provenance it does not have"
            )
        if self.kind is StepKind.SOURCE and not self.event_time_column:
            raise ValueError("source step must declare event_time_column")
        if self.kind is not StepKind.SOURCE and self.event_time_column:
            raise ValueError("only a source step may declare event_time_column")
        if self.kind is StepKind.WINDOWED and not self.window_end_column:
            raise ValueError(
                "windowed step must declare window_end_column -- a backward-looking "
                "window that will not say where it stopped cannot be verified"
            )
        if self.kind is not StepKind.WINDOWED and self.window_end_column:
            raise ValueError("only a windowed step may declare window_end_column")
        if self.kind is StepKind.WINDOWED and self.window_end_column not in self.adds_columns:
            raise ValueError("window_end_column must be among adds_columns")
        if self.kind is StepKind.TIME_INVARIANT and not self.justification:
            raise ValueError(
                "time-invariant step must record WHY its data needs no as-of anchor"
            )
        if self.kind is not StepKind.TIME_INVARIANT and self.justification:
            raise ValueError("only a time-invariant step carries a justification")
        if self.kind is StepKind.FILTER and self.adds_columns:
            raise ValueError("filter step must not add columns")
        missing = set(self.as_of_columns) - set(self.adds_columns)
        if self.kind in _ANCHOR_REQUIRED and missing:
            raise ValueError(
                f"as_of columns {sorted(missing)} are not among the columns this step adds"
            )
