"""Shared plumbing for every backward-looking (WINDOWED) step.

Extracted from `derivation.py` when the second family of windowed steps
landed. The extraction is not tidiness: `trailing_walk` below encodes the
ONE invariant that makes this whole subsystem trustworthy -- an
observation is appended to its group's history only AFTER the row that
produced it has been summarised -- and that invariant was previously
re-implemented, correctly, in each step. Re-implementing it N times is
how the N+1th copy gets it wrong.

The window-end and window-count suffixes live here too, because a step in
one module mirroring a step in another (see `OpponentFormStep.mirroring`)
has to agree with it about the column names.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import datetime

from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row

#: The last instant a window consumed. Published by every windowed step
#: and checked by the guard against the row's own tip-off.
WINDOW_END_SUFFIX = "__window_end"
#: How many observations actually contributed. Nulls are skipped rather
#: than zero-filled, so a "10-game average" over 3 games is a different
#: number and must be legible as one.
WINDOW_COUNT_SUFFIX = "__window_games"


def trailing_walk(
    frame: FeatureFrame,
    step_name: str,
    *,
    group_by: Sequence[str],
    observe: Callable[[Row], object],
) -> Iterator[tuple[int, Row, list[tuple[datetime, object]]]]:
    """Walk the frame in event order, handing each row its group's PRIOR
    observations.

    Yields `(original index, row, prior observations oldest-first)`. The
    row's own observation is appended only after the consumer resumes the
    generator, which is the structural reason no row can enter its own
    window: at the moment the consumer sees `past`, the current row is
    not in it and there is no ordering of the loop in which it could be.

    SIMULTANEOUS OBSERVATIONS ARE HELD BACK TOO, which is the part that
    is not obvious and that a "append after yield" implementation gets
    wrong. An observation becomes visible only once the walk reaches a
    row with a STRICTLY LATER event time, so two rows sharing an instant
    never enter each other's windows.

    That is not hypothetical. `RestDaysStep` already documents the common
    case -- a player-grain frame has ~12 rows per (team, tip-off) -- and
    this database contains a rarer one that breaks a per-PLAYER window:
    player 137 has ESPN box-score rows in games 21 and 22, both tipping
    off at 2024-08-23T23:30Z, on two different teams. Exactly one such
    collision exists in 31,340 rows, and it is enough to make a per-player
    rolling window publish a window end equal to the row's own tip-off,
    which the guard rejects. It rejects it correctly: two games played at
    the same instant cannot inform each other.

    Consumers must therefore SUMMARISE `past` before continuing the loop
    rather than keeping a reference to it -- the list is mutated in
    place on the next iteration, deliberately, so that a group's history
    is built once instead of copied per row.

    `group_by` naming a column the frame does not have would silently key
    every row on `(None,)` and produce one global history, so the caller
    is expected to have run `_require_columns` first.
    """
    history: dict[tuple[object, ...], list[tuple[datetime, object]]] = {}
    # Observed but not yet visible: recorded at an instant the walk has
    # not passed. `chronological` is ascending, so everything held is at
    # or before the current row's event time and only the strictly
    # earlier entries may be released.
    holding: dict[tuple[object, ...], list[tuple[datetime, object]]] = {}
    for index, row in chronological(frame, step_name):
        key = tuple(row.get(column) for column in group_by)
        past = history.setdefault(key, [])
        held = holding.setdefault(key, [])
        at = event_time(frame, row, step_name)
        released = 0
        for observed_at, observation in held:
            if observed_at >= at:
                break
            past.append((observed_at, observation))
            released += 1
        del held[:released]
        yield index, row, past
        held.append((at, observe(row)))


def finalise(cells: Sequence[Row | None], step_name: str) -> tuple[Row, ...]:
    """Positional results, refusing a gap.

    Every windowed step writes into a pre-sized list by ORIGINAL index,
    because it iterates in event order and the frame is not necessarily
    in event order. Filtering the Nones out instead of failing on them
    would silently SHIFT every later row's features onto the wrong game
    -- the kind of bug that leaves the pipeline green and the numbers
    subtly wrong.
    """
    if any(cell is None for cell in cells):
        missing = [i for i, cell in enumerate(cells) if cell is None]
        raise StepContractError(
            f"step {step_name!r} produced no cells for row(s) {missing[:5]}"
        )
    return tuple(cell for cell in cells if cell is not None)


def chronological(frame: FeatureFrame, step_name: str) -> list[tuple[int, Row]]:
    """(original index, row) ordered by event time.

    Sorting explicitly rather than trusting the loader's ORDER BY: a
    strategy is free to insert a step that reorders rows, and a rolling
    window fed out-of-order rows would happily average future games
    without any single line of code looking wrong. The original index
    comes along so results are written back positionally.
    """
    column = frame.event_time_column
    if column is None:
        raise StepContractError(f"step {step_name!r} requires an event-time column")
    return sorted(
        enumerate(frame.rows),
        key=lambda pair: (event_time(frame, pair[1], step_name), pair[0]),
    )


def event_time(frame: FeatureFrame, row: Row, step_name: str) -> datetime:
    value = row.get(frame.event_time_column or "")
    if not isinstance(value, datetime):
        raise StepContractError(
            f"step {step_name!r} needs a datetime event time in "
            f"{frame.event_time_column!r}, got {type(value).__name__}"
        )
    return value


def mean_of(values: Sequence[object]) -> float | None:
    """Arithmetic mean, or None for an empty sequence.

    None rather than 0.0: "no prior games" and "prior games averaging
    zero" are opposite claims, and a model given 0.0 for a team's first
    game of the season learns the second one.
    """
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)  # type: ignore[arg-type]


def numeric(values: Sequence[tuple[datetime, object]], key: str) -> list[float]:
    """Non-null floats for `key` across observations, oldest first.

    Observations are dicts of the columns a step chose to remember; a
    null means the source had no value (`pace` is null wherever
    balldontlie has no advanced-stats row), so it is skipped rather than
    zero-filled.
    """
    out: list[float] = []
    for _, observation in values:
        assert isinstance(observation, dict)
        value = observation.get(key)
        if value is not None:
            out.append(float(value))  # type: ignore[arg-type]
    return out


__all__ = [
    "WINDOW_COUNT_SUFFIX",
    "WINDOW_END_SUFFIX",
    "chronological",
    "event_time",
    "finalise",
    "mean_of",
    "numeric",
    "trailing_walk",
]
