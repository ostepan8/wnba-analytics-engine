"""The scheduler loop: one asyncio task per job, each firing on its own clock.

Design notes, all of them reactions to how the launchd arrangement failed:

* **One task per job, never a shared queue.** A slow weekly backfill must not
  delay the two-minute odds capture. Jobs are independent and stay that way.
* **A job never overlaps itself.** Each task runs its own steps sequentially and
  only then sleeps to the next fire, so a run that overruns delays that job and
  nothing else.
* **Every run is recorded, including failures.** The failure mode that cost a
  week of data was silence, not a bad exit code -- see
  db/migrations/0031_job_runs.sql.
* **A step's failure ends that run, not the process.** The scheduler stays up
  through a provider outage, a bad API key, or a database blip, and says so in
  job_runs rather than exiting and taking the healthy jobs with it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from wnba_engine.db.pool import Database
from wnba_engine.repositories import job_runs_repo
from wnba_engine.scheduler.config import Job, resolve_step

logger = logging.getLogger(__name__)

# Trailing stderr captured from a failing step, in bytes. journald has the
# whole thing; this is only what gets stored alongside the run.
STDERR_TAIL_BYTES = 8192


async def run_forever(jobs: tuple[Job, ...], db: Database) -> None:
    """Run every enabled job on its own schedule until cancelled."""
    enabled = tuple(job for job in jobs if job.enabled)
    skipped = tuple(job.name for job in jobs if not job.enabled)

    logger.info(
        "scheduler starting with %d job(s): %s", len(enabled), ", ".join(j.name for j in enabled)
    )
    if skipped:
        # Logged at startup, every start. A job that silently isn't running is
        # the exact failure this service was built to end, and "disabled on
        # purpose" only helps if someone reading the logs can see it.
        logger.warning("disabled in the schedule, NOT running: %s", ", ".join(skipped))

    async with asyncio.TaskGroup() as group:
        for job in enabled:
            group.create_task(_run_job_forever(job, db), name=f"job:{job.name}")


async def _run_job_forever(job: Job, db: Database) -> None:
    if job.run_at_start:
        # Fire immediately rather than waiting out a full period. Only set for
        # jobs whose missed window is unrecoverable -- market capture reads
        # feeds with no historical endpoint, so a skipped fire is lost forever.
        await _execute(job, db)

    while True:
        delay = seconds_until_next_fire(job, datetime.now(UTC))
        logger.debug("%s: sleeping %.0fs until next fire", job.name, delay)
        await asyncio.sleep(delay)
        await _execute(job, db)


async def _execute(job: Job, db: Database) -> None:
    """Run one pass of a job's steps and record the outcome. Never raises."""
    started = time.monotonic()
    run_id = _open_run(job, db)

    try:
        exit_code, error = await _run_steps(job)
        status = "ok" if exit_code == 0 else ("timeout" if exit_code is None else "failed")
    except Exception as exc:  # noqa: BLE001 -- one job's crash must not stop the rest
        logger.exception("%s: scheduler-side failure", job.name)
        exit_code, error, status = None, f"scheduler error: {exc}", "failed"

    duration = time.monotonic() - started
    _log_outcome(job, status, duration, error)
    _settle_run(db, run_id, status=status, exit_code=exit_code, duration=duration, error=error)


async def _run_steps(job: Job) -> tuple[int | None, str | None]:
    """Run a job's steps in order, stopping at the first failure.

    Returns (exit_code, error). exit_code is None if the step was killed for
    exceeding the job's timeout -- the process never got to return one.
    """
    deadline = time.monotonic() + job.timeout_seconds

    for step in job.steps:
        command = resolve_step(step)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, f"timed out after {job.timeout_seconds}s before step: {' '.join(command)}"

        logger.info("%s: %s", job.name, " ".join(command))
        code, stderr = await _run_one(command, remaining)
        if code is None:
            return None, f"timed out after {job.timeout_seconds}s during: {' '.join(command)}"
        if code != 0:
            return code, f"step failed (exit {code}): {' '.join(command)}\n{stderr}"

    return 0, None


async def _run_one(command: tuple[str, ...], timeout: float) -> tuple[int | None, str]:
    """Run one subprocess, killing it if it outlives the remaining budget.

    stdout is inherited so step output lands in journald as it happens; stderr
    is captured so a failure can be stored with the run.
    """
    process = await asyncio.create_subprocess_exec(*command, stderr=asyncio.subprocess.PIPE)
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        # kill(), not terminate(): these are network-bound ingest commands and
        # a SIGTERM they choose to ignore would hold the job's slot open.
        process.kill()
        await process.wait()
        return None, ""
    return process.returncode, stderr[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")


def seconds_until_next_fire(job: Job, now: datetime) -> float:
    """How long to wait before this job's next run."""
    trigger = job.trigger
    if trigger.every_seconds is not None:
        return float(trigger.every_seconds)
    if trigger.daily_at is not None:
        hour, minute = trigger.daily_at
        return _seconds_until(now, _next_daily(now, hour, minute))
    if trigger.weekly_at is not None:
        weekday, hour, minute = trigger.weekly_at
        return _seconds_until(now, _next_weekly(now, weekday, hour, minute))
    raise AssertionError(f"job {job.name!r} has no trigger")  # pragma: no cover


def _next_daily(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _next_weekly(now: datetime, weekday: int, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (weekday - candidate.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    return candidate if candidate > now else candidate + timedelta(days=7)


def _seconds_until(now: datetime, target: datetime) -> float:
    return max(0.0, (target - now).total_seconds())


def _open_run(job: Job, db: Database) -> int | None:
    """Open a run record. A database that is briefly unreachable must not stop
    the job from running -- losing the record is strictly better than losing the
    capture window it would have described."""
    try:
        with db.connection() as conn:
            return job_runs_repo.open_run(conn, job.name)
    except Exception:  # noqa: BLE001 -- bookkeeping must never block the work
        logger.exception("%s: could not record run start", job.name)
        return None


def _settle_run(
    db: Database,
    run_id: int | None,
    *,
    status: str,
    exit_code: int | None,
    duration: float,
    error: str | None,
) -> None:
    if run_id is None:
        return
    try:
        with db.connection() as conn:
            job_runs_repo.settle_run(
                conn,
                run_id,
                status=status,
                exit_code=exit_code,
                duration_seconds=duration,
                error=error,
            )
    except Exception:  # noqa: BLE001 -- see _open_run
        logger.exception("could not record outcome for run %s", run_id)


def _log_outcome(job: Job, status: str, duration: float, error: str | None) -> None:
    if status == "ok":
        logger.info("%s: ok in %.1fs", job.name, duration)
    else:
        logger.error("%s: %s after %.1fs -- %s", job.name, status, duration, error)
