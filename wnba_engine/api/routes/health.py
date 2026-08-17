"""Liveness, and the pipeline-health endpoint this project actually needed.

/health/jobs is the one that matters. The engine's real failure mode is not a
crash -- it is six schedulers quietly doing nothing while the API stays up and
answers every query with data that stopped moving a week ago. Freshness of the
data cannot detect that either: the WNBA off-season looks identical to a dead
scheduler. Only a record of job *execution* separates them.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Response
from psycopg import Connection

from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import job_runs_repo
from wnba_engine.scheduler.config import ScheduleError, load_jobs

router = APIRouter(tags=["health"])

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_PATH = Path(__file__).resolve().parents[3] / "deploy" / "schedule.toml"


@router.get("/health")
def health(conn: Connection = Depends(get_connection)) -> dict[str, object]:
    """Liveness plus a real database round-trip.

    Deliberately queries rather than just returning 200: an API that reports
    healthy while its database is unreachable is worse than one that is simply
    down, because it silences the thing watching it.
    """
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "reachable"}


@router.get("/health/jobs")
def job_health(
    response: Response, conn: Connection = Depends(get_connection)
) -> dict[str, object]:
    """Last run, last success, and recent failure count for every scheduled job.

    Joined against the schedule itself, not just the run history, because the
    two answer different questions and only the pair is trustworthy:

      * history alone omits a job that has NEVER run -- the most complete
        failure there is, and the one that would leave no row here at all;
      * the schedule alone cannot say whether a job that should be running is.

    Merging them also separates "failing" from "switched off on purpose". A
    disabled job carrying old failures would otherwise show a red light forever.
    """
    # Short cache: this is the endpoint someone reloads when they suspect a
    # problem, and a stale answer there is actively misleading.
    response.headers["Cache-Control"] = "public, max-age=15"
    return _merge_with_schedule(job_runs_repo.fetch_health(conn))


def _merge_with_schedule(history: list[dict[str, Any]]) -> dict[str, object]:
    scheduled = _load_schedule()
    by_name = {row["job_name"]: dict(row) for row in history}

    for name, job in scheduled.items():
        row = by_name.setdefault(name, {"job_name": name, "last_status": None})
        row["scheduled"] = True
        row["enabled"] = job.enabled
        row["description"] = job.description

    # A job with runs but no schedule entry was renamed or removed; its history
    # stays visible rather than vanishing, flagged as no longer scheduled.
    for name, row in by_name.items():
        row.setdefault("scheduled", name in scheduled)
        row.setdefault("enabled", False)
        row.setdefault("description", "")

    jobs = sorted(by_name.values(), key=lambda row: str(row["job_name"]))
    return {
        "jobs": jobs,
        # Only counts jobs that are supposed to be running. A deliberately
        # disabled job must not hold the whole pipeline red.
        "any_failing": any(
            job.get("enabled") and job.get("last_status") in ("failed", "timeout")
            for job in jobs
        ),
        "never_run": [
            job["job_name"] for job in jobs if job.get("enabled") and not job.get("last_status")
        ],
    }


def _load_schedule() -> dict[str, Any]:
    """Best-effort: the run history is still worth serving without it."""
    path = Path(os.environ.get("WNBA_SCHEDULE_PATH", DEFAULT_SCHEDULE_PATH))
    try:
        # The API describes the schedule; it never runs it, and has none of the
        # scheduler's environment. Validating {env:...} placeholders here would
        # report a perfectly good schedule as unreadable.
        return {job.name: job for job in load_jobs(path, validate_environment=False)}
    except (ScheduleError, OSError):
        logger.warning("could not read the schedule at %s; reporting run history only", path)
        return {}
