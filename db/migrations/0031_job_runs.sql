-- Execution record for every scheduled ingest job.
--
-- This table exists because of a specific, repeated failure. Scheduling
-- lived in launchd plists across two laptops, each hardcoding a repo path.
-- When the repo moved, `wnba-market-sync` and `wnba-odds-focused` began
-- exiting 78 (EX_CONFIG) and the three `*-sync.sh` wrappers began exiting
-- *0* on their `[ -d "$PROJECT_DIR" ] || exit 0` guard. Nothing anywhere
-- observed either case. The database's newest row sat at 2026-08-10 for a
-- week while capture kept writing files that nothing read -- the second
-- such gap, after a four-day one on 2026-08-03.
--
-- The lesson is not "use a better scheduler". It is that a pipeline with no
-- record of its own execution cannot tell "nothing happened" apart from
-- "nothing was supposed to happen". Freshness of the DATA is not a proxy
-- either: the off-season looks exactly like a dead scheduler.
--
-- So every run writes a row here, including runs that fail, and the API's
-- /health/jobs reads it. A job that stops firing entirely shows up as a
-- stale started_at, which no exit code could have told us.
--
-- Append-only. A run is INSERTed as 'running' and UPDATEd exactly once when
-- it settles; history is never rewritten or pruned by the scheduler.

CREATE TABLE job_runs (
    id              BIGSERIAL PRIMARY KEY,

    job_name        TEXT        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,

    -- 'running' until the run settles. 'timeout' is deliberately distinct
    -- from 'failed': a job that ran too long and one that returned an error
    -- call for different fixes, and collapsing them hides the difference.
    status          TEXT        NOT NULL
                    CHECK (status IN ('running', 'ok', 'failed', 'timeout')),

    -- NULL while running, and for a timeout (the process was killed, so it
    -- never produced one).
    exit_code       INTEGER,

    duration_seconds NUMERIC(10,3),

    -- Trailing stderr from a failed run. Truncated by the writer -- this is
    -- a signal for a human deciding whether to look, not a log store.
    error           TEXT,

    CONSTRAINT job_runs_finished_with_status CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status <> 'running' AND finished_at IS NOT NULL)
    )
);

-- The only read pattern that matters: "latest run(s) for this job".
CREATE INDEX job_runs_job_name_started_at_idx
    ON job_runs (job_name, started_at DESC);

-- Health at a glance, one row per job that has ever run.
--
-- last_success_at is separate from last_run_at on purpose. A job failing
-- every fire still has a fresh last_run_at, so last_run_at alone reports a
-- broken pipeline as healthy -- which is exactly the mistake this whole
-- table is here to stop making.
CREATE VIEW job_health AS
SELECT
    job_name,
    max(started_at)                                        AS last_run_at,
    max(started_at) FILTER (WHERE status = 'ok')           AS last_success_at,
    (array_agg(status ORDER BY started_at DESC))[1]        AS last_status,
    (array_agg(error  ORDER BY started_at DESC))[1]        AS last_error,
    count(*) FILTER (WHERE status IN ('failed', 'timeout')
                     AND started_at > now() - INTERVAL '24 hours') AS failures_24h,
    count(*) FILTER (WHERE started_at > now() - INTERVAL '24 hours') AS runs_24h
FROM job_runs
GROUP BY job_name;
