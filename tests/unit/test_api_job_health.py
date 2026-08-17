"""/health/jobs merges run history with the schedule, and the merge is the point.

Run history alone cannot report the worst failure there is -- a job that has
never run at all leaves no row to be stale. The schedule alone cannot say
whether a job that should be running is. Reading either one on its own is how a
dead pipeline looked healthy for a week.
"""

from __future__ import annotations

from wnba_engine.api.routes import health
from wnba_engine.scheduler.config import Job, Trigger


def job(name: str, *, enabled: bool = True) -> Job:
    return Job(
        name=name,
        trigger=Trigger(every_seconds=120),
        steps=(("wnba-engine", name),),
        timeout_seconds=60,
        run_at_start=False,
        description=f"{name} description",
        enabled=enabled,
    )


def merge(history, schedule, monkeypatch):
    monkeypatch.setattr(health, "_load_schedule", lambda: {j.name: j for j in schedule})
    return health._merge_with_schedule(history)


def test_a_scheduled_job_that_never_ran_is_reported(monkeypatch) -> None:
    """It has no row in job_health at all, so history alone would omit it
    entirely -- indistinguishable from a job nobody ever configured."""
    result = merge([], [job("espn-sync")], monkeypatch)

    assert [j["job_name"] for j in result["jobs"]] == ["espn-sync"]
    assert result["never_run"] == ["espn-sync"]
    assert result["jobs"][0]["scheduled"] is True


def test_a_disabled_job_is_not_reported_as_failing(monkeypatch) -> None:
    """Its old failures stay visible, but a job switched off on purpose must not
    hold the whole pipeline red."""
    history = [{"job_name": "odds-focused", "last_status": "failed", "failures_24h": 7}]
    result = merge(history, [job("odds-focused", enabled=False)], monkeypatch)

    assert result["any_failing"] is False
    assert result["never_run"] == []
    assert result["jobs"][0]["enabled"] is False
    assert result["jobs"][0]["last_status"] == "failed"


def test_an_enabled_job_that_is_failing_sets_any_failing(monkeypatch) -> None:
    history = [{"job_name": "capture-ingest", "last_status": "failed"}]
    result = merge(history, [job("capture-ingest")], monkeypatch)
    assert result["any_failing"] is True


def test_a_timing_out_job_counts_as_failing(monkeypatch) -> None:
    history = [{"job_name": "balldontlie-season", "last_status": "timeout"}]
    result = merge(history, [job("balldontlie-season")], monkeypatch)
    assert result["any_failing"] is True


def test_history_for_a_job_no_longer_scheduled_is_kept_but_flagged(monkeypatch) -> None:
    """A renamed or removed job keeps its history rather than silently vanishing,
    marked as no longer scheduled so it is not mistaken for a live one."""
    history = [{"job_name": "wnba-market-sync", "last_status": "failed"}]
    result = merge(history, [job("capture-ingest")], monkeypatch)

    retired = next(j for j in result["jobs"] if j["job_name"] == "wnba-market-sync")
    assert retired["scheduled"] is False
    assert retired["enabled"] is False
    # Retired history must not raise the alarm for the running pipeline.
    assert result["any_failing"] is False


def test_an_unreadable_schedule_still_serves_run_history(monkeypatch) -> None:
    """Degraded, not broken: losing the schedule file should not also lose the
    record of what actually ran."""
    history = [{"job_name": "market-capture", "last_status": "ok"}]
    result = merge(history, [], monkeypatch)

    assert [j["job_name"] for j in result["jobs"]] == ["market-capture"]
    assert result["jobs"][0]["scheduled"] is False
