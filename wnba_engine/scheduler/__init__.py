"""Always-on job scheduler for the ingest pipeline.

Replaces six launchd agents that were split across two laptops. See
wnba_engine/scheduler/config.py for why the schedule is a data file, and
db/migrations/0031_job_runs.sql for why every run is recorded.
"""
