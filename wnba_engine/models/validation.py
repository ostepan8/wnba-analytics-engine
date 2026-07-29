"""Data-quality check result shapes.

Each check is a SQL invariant against the real data (cross-source
consistency, referential integrity, or plausibility bounds) -- not a
schema constraint Postgres already enforces. A check that finds nothing
wrong passes with violation_count=0; sample_violations is capped so a
check that fails on thousands of rows doesn't flood the report.

A violation can be individually acknowledged as known-benign (see
wnba_engine/validation/acknowledged.py). Acknowledged ones still count
toward violation_count and are still reported -- they just don't fail
the check, so `validate` stays usable as a gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_SAMPLE_VIOLATIONS = 10


@dataclass(frozen=True, slots=True)
class CheckResult:
    """`violation_count` is every violation found, acknowledged or not --
    it's the honest count of what the query matched. `passed` keys off
    `unacknowledged_count` instead, so a database whose only remaining
    violations are individually verified reports green without that
    verification being invisible.
    """

    name: str
    description: str
    passed: bool
    violation_count: int
    sample_violations: tuple[str, ...]
    acknowledged_count: int = 0
    sample_acknowledged: tuple[str, ...] = field(default=())
    matched_acknowledgements: tuple[str, ...] = field(default=())

    @property
    def unacknowledged_count(self) -> int:
        return self.violation_count - self.acknowledged_count


@dataclass(frozen=True, slots=True)
class ValidationReport:
    checks: tuple[CheckResult, ...]
    stale_acknowledgements: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def acknowledged_count(self) -> int:
        return sum(check.acknowledged_count for check in self.checks)
