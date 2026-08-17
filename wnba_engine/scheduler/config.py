"""Schedule definitions, parsed from a TOML file.

The schedule is data, not code, and it lives in the repo next to the commands
it runs. That is a deliberate reaction to what it replaces: six launchd plists
spread across two laptops, each embedding an absolute path to a checkout, which
is how the pipeline died silently for a week (db/migrations/0031_job_runs.sql).
Nothing here names a machine, a user, or a directory.

Placeholders, resolved per run rather than at load, so a long-lived scheduler
does not freeze last week's date into a command:

    {season}       current UTC year, e.g. 2026
    {today}        current UTC date, YYYY-MM-DD
    {days_ago:N}   N days before today, UTC, YYYY-MM-DD
    {env:NAME}     value of environment variable NAME; startup fails if unset
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PLACEHOLDER_RE = re.compile(r"\{(season|today|days_ago:\d+|env:[A-Za-z_][A-Za-z0-9_]*)\}")


class ScheduleError(ValueError):
    """A schedule file that cannot be trusted to run. Always fatal at startup."""


@dataclass(frozen=True, slots=True)
class Trigger:
    """When a job fires. Exactly one of these three forms is set."""

    every_seconds: int | None = None
    daily_at: tuple[int, int] | None = None  # (hour, minute), UTC
    weekly_at: tuple[int, int, int] | None = None  # (weekday 0=mon, hour, minute), UTC


@dataclass(frozen=True, slots=True)
class Job:
    name: str
    trigger: Trigger
    steps: tuple[tuple[str, ...], ...]
    timeout_seconds: int
    run_at_start: bool
    description: str
    # A disabled job is still parsed and validated, then never scheduled. It
    # stays in this file with its reason attached rather than being deleted or
    # commented out, so "why isn't this running?" has an answer in the same
    # place as the schedule itself.
    enabled: bool = True


def load_jobs(
    path: Path,
    *,
    environ: dict[str, str] | None = None,
    validate_environment: bool = True,
) -> tuple[Job, ...]:
    """Parse and fully validate a schedule file. Raises ScheduleError on anything
    suspect -- an unparseable schedule must stop the service, not start it with
    half the pipeline running.

    `validate_environment=False` skips only the check that every {env:NAME}
    placeholder resolves. Readers that describe the schedule without running it
    -- the API's /health/jobs, which needs names and enabled flags -- would
    otherwise have to fabricate the scheduler's environment to read a file, and
    would report "schedule unavailable" for a schedule that is perfectly fine.
    The scheduler itself always validates."""
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ScheduleError(f"cannot read schedule {path}: {exc}") from exc

    entries = raw.get("jobs")
    if not isinstance(entries, list) or not entries:
        raise ScheduleError(f"{path}: expected a non-empty [[jobs]] array")

    jobs = tuple(_parse_job(entry, path) for entry in entries)
    _reject_duplicate_names(jobs, path)
    if validate_environment:
        # Resolve every placeholder once at startup purely to validate it. A
        # {env:...} typo must fail here, not silently at 3am on a weekly job.
        for job in jobs:
            for step in job.steps:
                resolve_step(step, environ=environ)
    return jobs


def resolve_step(
    step: tuple[str, ...],
    *,
    now: datetime | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Substitute placeholders in one command, at the moment it is about to run."""
    moment = now or datetime.now(UTC)
    env = os.environ if environ is None else environ
    return tuple(_resolve_token(token, moment, env) for token in step)


def _resolve_token(token: str, now: datetime, env: dict[str, str] | os._Environ) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "season":
            return str(now.year)
        if key == "today":
            return now.date().isoformat()
        if key.startswith("days_ago:"):
            return _days_ago(now.date(), int(key.split(":", 1)[1]))
        name = key.split(":", 1)[1]
        value = env.get(name)
        if value is None:
            raise ScheduleError(
                f"environment variable {name} is referenced by the schedule but unset"
            )
        return value

    return _PLACEHOLDER_RE.sub(replace, token)


def _days_ago(today: date, days: int) -> str:
    return (today - timedelta(days=days)).isoformat()


def _parse_job(entry: object, path: Path) -> Job:
    if not isinstance(entry, dict):
        raise ScheduleError(f"{path}: each [[jobs]] entry must be a table")

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScheduleError(f"{path}: every job needs a non-empty name")

    steps = _parse_steps(entry.get("steps"), name, path)
    trigger = _parse_trigger(entry, name, path)
    timeout = _parse_duration(entry.get("timeout", "15m"), f"{name}.timeout", path)
    _reject_overlapping_timeout(trigger, timeout, name, path)

    return Job(
        name=name,
        trigger=trigger,
        steps=steps,
        timeout_seconds=timeout,
        run_at_start=bool(entry.get("run_at_start", False)),
        description=str(entry.get("description", "")).strip(),
        enabled=bool(entry.get("enabled", True)),
    )


def _parse_steps(value: object, name: str, path: Path) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or not value:
        raise ScheduleError(f"{path}: job {name!r} needs a non-empty steps list")
    steps: list[tuple[str, ...]] = []
    for step in value:
        if not isinstance(step, list) or not step or not all(isinstance(t, str) for t in step):
            raise ScheduleError(f"{path}: job {name!r} has a step that is not a list of strings")
        steps.append(tuple(step))
    return tuple(steps)


def _parse_trigger(entry: dict[str, object], name: str, path: Path) -> Trigger:
    forms = [key for key in ("every", "daily_at", "weekly_at") if key in entry]
    if len(forms) != 1:
        raise ScheduleError(
            f"{path}: job {name!r} must set exactly one of every / daily_at / weekly_at, "
            f"got {forms or 'none'}"
        )
    form = forms[0]
    if form == "every":
        return Trigger(every_seconds=_parse_duration(entry["every"], f"{name}.every", path))
    if form == "daily_at":
        return Trigger(daily_at=_parse_clock(entry["daily_at"], f"{name}.daily_at", path))
    return Trigger(weekly_at=_parse_weekly(entry["weekly_at"], f"{name}.weekly_at", path))


def _parse_duration(value: object, field: str, path: Path) -> int:
    if not isinstance(value, str) or not (match := _DURATION_RE.match(value.strip())):
        raise ScheduleError(f"{path}: {field} must look like '30m', '2h' or '90s', got {value!r}")
    amount, unit = match.groups()
    seconds = int(amount) * _DURATION_SECONDS[unit]
    if seconds <= 0:
        raise ScheduleError(f"{path}: {field} must be greater than zero")
    return seconds


def _parse_clock(value: object, field: str, path: Path) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ScheduleError(f"{path}: {field} must be a 'HH:MM' string, got {value!r}")
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except ValueError as exc:
        raise ScheduleError(f"{path}: {field} must be 'HH:MM' (UTC), got {value!r}") from exc
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ScheduleError(f"{path}: {field} is not a valid time of day: {value!r}")
    return hour, minute


def _parse_weekly(value: object, field: str, path: Path) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(parts := value.strip().split()) != 2:
        raise ScheduleError(
            f"{path}: {field} must be '<day> HH:MM', e.g. 'sun 09:00', got {value!r}"
        )
    day_text, clock_text = parts
    if (day := day_text.lower()[:3]) not in WEEKDAYS:
        raise ScheduleError(
            f"{path}: {field} has an unknown day {day_text!r}; use one of {WEEKDAYS}"
        )
    hour, minute = _parse_clock(clock_text, field, path)
    return WEEKDAYS.index(day), hour, minute


def _reject_overlapping_timeout(trigger: Trigger, timeout: int, name: str, path: Path) -> None:
    """An interval job whose timeout exceeds its own period would queue behind
    itself forever. The runner already refuses to overlap a job with itself, so
    this would silently halve the effective cadence instead of erroring."""
    if trigger.every_seconds is not None and timeout > trigger.every_seconds:
        raise ScheduleError(
            f"{path}: job {name!r} has a {timeout}s timeout but fires every "
            f"{trigger.every_seconds}s -- it would skip its own next run"
        )


def _reject_duplicate_names(jobs: tuple[Job, ...], path: Path) -> None:
    seen: set[str] = set()
    for job in jobs:
        if job.name in seen:
            raise ScheduleError(f"{path}: duplicate job name {job.name!r}")
        seen.add(job.name)
