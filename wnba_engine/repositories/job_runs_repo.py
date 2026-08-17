"""Execution records for scheduled jobs. See db/migrations/0031_job_runs.sql
for why this is recorded at all.

A run is opened before the work starts and settled exactly once afterwards,
so a job that dies mid-run leaves a visible 'running' row rather than no
trace. That asymmetry is the point: the failure this guards against is
silence, not a bad exit code.
"""

from __future__ import annotations

from psycopg import Connection

# Trailing stderr kept with a failure. Enough to recognise a known error
# without turning this table into a log store -- the full output is in
# journald, which is where someone debugging should actually look.
MAX_ERROR_CHARS = 2000

_OPEN_RUN = """
INSERT INTO job_runs (job_name, status)
VALUES (%s, 'running')
RETURNING id
"""

_SETTLE_RUN = """
UPDATE job_runs
   SET status = %s,
       finished_at = now(),
       exit_code = %s,
       duration_seconds = %s,
       error = %s
 WHERE id = %s
"""

_SELECT_HEALTH = """
SELECT job_name, last_run_at, last_success_at, last_status, last_error,
       failures_24h, runs_24h
  FROM job_health
 ORDER BY job_name
"""


def open_run(conn: Connection, job_name: str) -> int:
    """Record that a job has started. Returns the run id used to settle it."""
    row = conn.execute(_OPEN_RUN, (job_name,)).fetchone()
    if row is None:  # pragma: no cover -- RETURNING always yields a row
        raise RuntimeError(f"failed to open a job run for {job_name!r}")
    conn.commit()
    return int(row[0])


def settle_run(
    conn: Connection,
    run_id: int,
    *,
    status: str,
    exit_code: int | None,
    duration_seconds: float,
    error: str | None,
) -> None:
    """Close out a run. Called exactly once per open_run, including on failure."""
    conn.execute(
        _SETTLE_RUN,
        (
            status,
            exit_code,
            round(duration_seconds, 3),
            _truncate(error),
            run_id,
        ),
    )
    conn.commit()


def fetch_health(conn: Connection) -> list[dict[str, object]]:
    """One row per job that has ever run, newest state first. Read by the API."""
    cursor = conn.execute(_SELECT_HEALTH)
    columns = [description.name for description in cursor.description or ()]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _truncate(error: str | None) -> str | None:
    if error is None:
        return None
    trimmed = error.strip()
    if not trimmed:
        return None
    if len(trimmed) <= MAX_ERROR_CHARS:
        return trimmed
    # Keep the TAIL, not the head: a traceback's final lines name the actual
    # exception, while the first lines are the same framework frames every time.
    return "...(truncated)...\n" + trimmed[-MAX_ERROR_CHARS:]
