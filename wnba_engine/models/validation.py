"""Data-quality check result shapes.

Each check is a SQL invariant against the real data (cross-source
consistency, referential integrity, or plausibility bounds) -- not a
schema constraint Postgres already enforces. A check that finds nothing
wrong passes with violation_count=0; sample_violations is capped so a
check that fails on thousands of rows doesn't flood the report.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_SAMPLE_VIOLATIONS = 10


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    description: str
    passed: bool
    violation_count: int
    sample_violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)
