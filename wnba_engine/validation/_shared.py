"""Shared helper for turning a query's violation rows into a CheckResult.
Not a public module -- import from the checks modules, not directly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from wnba_engine.models.validation import MAX_SAMPLE_VIOLATIONS, CheckResult
from wnba_engine.validation import acknowledged as ack

Row = tuple[object, ...]


def build_check_result(
    *,
    name: str,
    description: str,
    rows: Sequence[Row],
    formatter: Callable[[Row], str],
    key_fn: Callable[[Row], str] | None = None,
) -> CheckResult:
    """Assemble a CheckResult, splitting rows into acknowledged and
    unacknowledged buckets.

    `key_fn` derives the stable identity a row is acknowledged under (see
    wnba_engine/validation/acknowledged.py). Omit it and no row can be
    acknowledged -- every violation fails the check, which is the right
    default for a check with no known-benign cases.
    """
    if key_fn is None:
        return CheckResult(
            name=name,
            description=description,
            passed=not rows,
            violation_count=len(rows),
            sample_violations=tuple(formatter(row) for row in rows[:MAX_SAMPLE_VIOLATIONS]),
        )

    known_keys = ack.acknowledged_keys(name)
    keyed = [(key_fn(row), row) for row in rows]
    unacknowledged = [row for key, row in keyed if key not in known_keys]
    acknowledged = [(key, row) for key, row in keyed if key in known_keys]

    return CheckResult(
        name=name,
        description=description,
        passed=not unacknowledged,
        violation_count=len(rows),
        sample_violations=tuple(formatter(row) for row in unacknowledged[:MAX_SAMPLE_VIOLATIONS]),
        acknowledged_count=len(acknowledged),
        sample_acknowledged=tuple(
            _describe(name, formatter(row), key)
            for key, row in acknowledged[:MAX_SAMPLE_VIOLATIONS]
        ),
        matched_acknowledgements=tuple(key for key, _ in acknowledged),
    )


def _describe(check_name: str, rendered: str, key: str) -> str:
    """Render an acknowledged violation with the reason it was cleared,
    so a muted row is still legible in the report rather than invisible.
    """
    entry = ack.lookup(check_name, key)
    return f"{rendered} [{entry.reason}]" if entry else rendered
