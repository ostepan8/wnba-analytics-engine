"""Shared helper for turning a query's violation rows into a CheckResult.
Not a public module -- import from the checks modules, not directly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from wnba_engine.models.validation import MAX_SAMPLE_VIOLATIONS, CheckResult


def build_check_result(
    *,
    name: str,
    description: str,
    rows: Sequence[tuple[object, ...]],
    formatter: Callable[[tuple[object, ...]], str],
) -> CheckResult:
    return CheckResult(
        name=name,
        description=description,
        passed=not rows,
        violation_count=len(rows),
        sample_violations=tuple(formatter(row) for row in rows[:MAX_SAMPLE_VIOLATIONS]),
    )
