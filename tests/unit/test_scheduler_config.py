"""The schedule file is the pipeline's single source of truth about what runs.

It replaced six launchd plists whose failure mode was silence: a plist pointing
at a moved checkout kept "succeeding" while doing nothing, and the database sat
frozen for a week. So the parser's contract is that anything it cannot fully
verify is a startup error, never a warning -- a scheduler that starts with half
a schedule reproduces exactly the failure it exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from wnba_engine.scheduler.config import ScheduleError, load_jobs, resolve_step
from wnba_engine.scheduler.runner import seconds_until_next_fire

REPO_SCHEDULE = Path(__file__).resolve().parents[2] / "deploy" / "schedule.toml"

# 2026-08-17 is a Monday, which the weekly assertions below depend on.
MONDAY_0055_UTC = datetime(2026, 8, 17, 0, 55, tzinfo=UTC)


def write_schedule(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "schedule.toml"
    path.write_text(body)
    return path


class TestRepoSchedule:
    """The schedule actually shipped must parse -- a deploy is too late to find out."""

    def test_parses(self) -> None:
        jobs = load_jobs(REPO_SCHEDULE, environ={"WNBA_CAPTURE_ROOT": "/data/captures"})
        assert {job.name for job in jobs} == {
            "market-capture",
            "capture-ingest",
            "venue-prices",
            "odds-focused",
            "market-injury-snapshot",
            "espn-sync",
            "balldontlie-season",
        }

    def test_free_venue_work_is_not_behind_the_metered_capture(self) -> None:
        """These ran as one job until a deactivated the-odds-api key failed at
        the first step and stopped the two free steps behind it, costing seven
        days of Kalshi and Polymarket fills that were never unavailable. Free
        work must not queue behind paid work."""
        jobs = load_jobs(REPO_SCHEDULE, environ={"WNBA_CAPTURE_ROOT": "/data/captures"})
        venue = next(job for job in jobs if job.name == "venue-prices")
        commands = {step[1] for step in venue.steps}
        assert commands == {"refresh-venue-prices", "log-divergences"}
        assert not any("capture-odds-focused" in step for step in venue.steps)

    def test_only_unrecoverable_capture_runs_at_start(self) -> None:
        """Market capture reads feeds with no historical endpoint, so a skipped
        fire is lost permanently and it catches up immediately after a restart.
        Every other job can be backfilled and must not spend a request on reload."""
        jobs = load_jobs(REPO_SCHEDULE, environ={"WNBA_CAPTURE_ROOT": "/data/captures"})
        at_start = {job.name for job in jobs if job.run_at_start}
        assert at_start == {"market-capture"}

    def test_a_disabled_job_still_parses_and_validates(self, tmp_path: Path) -> None:
        """Disabling is not deleting. The job keeps its definition and its
        reason in the schedule file so re-enabling is a one-word edit, and a
        broken command in it is still caught at startup."""
        path = write_schedule(
            tmp_path,
            '[[jobs]]\nname = "paid"\nenabled = false\nevery = "2m"\n'
            'timeout = "110s"\nsteps = [["echo", "hi"]]\n',
        )
        job = load_jobs(path)[0]
        assert job.enabled is False

    def test_jobs_default_to_enabled(self, tmp_path: Path) -> None:
        path = write_schedule(
            tmp_path, '[[jobs]]\nname = "x"\nevery = "1h"\nsteps = [["echo", "hi"]]\n'
        )
        assert load_jobs(path)[0].enabled is True

    def test_odds_capture_finishes_inside_its_own_period(self) -> None:
        """The two-minute cadence is load-bearing: the cross-venue follow-through
        is 15-20 minutes wide, so the sampling interval must stay a small
        fraction of it. A run that outlives its period silently halves it."""
        jobs = load_jobs(REPO_SCHEDULE, environ={"WNBA_CAPTURE_ROOT": "/data/captures"})
        odds = next(job for job in jobs if job.name == "odds-focused")
        assert odds.trigger.every_seconds == 120
        assert odds.timeout_seconds < 120


class TestPlaceholders:
    def test_dates_resolve_at_fire_time_not_load_time(self) -> None:
        step = ("wnba-engine", "backfill-odds", "--since", "{days_ago:2}", "--until", "{today}")
        assert resolve_step(step, now=MONDAY_0055_UTC) == (
            "wnba-engine",
            "backfill-odds",
            "--since",
            "2026-08-15",
            "--until",
            "2026-08-17",
        )

    def test_season_is_the_current_utc_year(self) -> None:
        resolved = resolve_step(("--season", "{season}"), now=MONDAY_0055_UTC)
        assert resolved == ("--season", "2026")

    def test_environment_placeholder_is_substituted(self) -> None:
        resolved = resolve_step(
            ("--root", "{env:WNBA_CAPTURE_ROOT}"),
            environ={"WNBA_CAPTURE_ROOT": "/data/captures"},
        )
        assert resolved == ("--root", "/data/captures")

    def test_missing_environment_variable_is_fatal(self, tmp_path: Path) -> None:
        """Caught at startup rather than at 3am on a weekly job's first fire."""
        path = write_schedule(
            tmp_path,
            '[[jobs]]\nname = "x"\nevery = "1h"\nsteps = [["echo", "{env:NOT_SET_ANYWHERE}"]]\n',
        )
        with pytest.raises(ScheduleError, match="NOT_SET_ANYWHERE"):
            load_jobs(path, environ={})


class TestValidation:
    """Every one of these would otherwise start a scheduler that runs the wrong
    thing, or nothing, without saying so."""

    def test_rejects_a_timeout_longer_than_its_own_period(self, tmp_path: Path) -> None:
        path = write_schedule(
            tmp_path,
            '[[jobs]]\nname = "x"\nevery = "2m"\ntimeout = "5m"\nsteps = [["echo", "hi"]]\n',
        )
        with pytest.raises(ScheduleError, match="skip its own next run"):
            load_jobs(path)

    def test_rejects_two_triggers_on_one_job(self, tmp_path: Path) -> None:
        path = write_schedule(
            tmp_path,
            '[[jobs]]\nname = "x"\nevery = "1h"\ndaily_at = "08:00"\nsteps = [["echo", "hi"]]\n',
        )
        with pytest.raises(ScheduleError, match="exactly one of"):
            load_jobs(path)

    def test_rejects_a_job_with_no_trigger(self, tmp_path: Path) -> None:
        path = write_schedule(tmp_path, '[[jobs]]\nname = "x"\nsteps = [["echo", "hi"]]\n')
        with pytest.raises(ScheduleError, match="exactly one of"):
            load_jobs(path)

    def test_rejects_duplicate_job_names(self, tmp_path: Path) -> None:
        """Two jobs sharing a name would collapse into one line in job_health,
        hiding whichever of them stopped running."""
        path = write_schedule(
            tmp_path,
            '[[jobs]]\nname = "x"\nevery = "1h"\nsteps = [["echo", "a"]]\n'
            '[[jobs]]\nname = "x"\nevery = "2h"\nsteps = [["echo", "b"]]\n',
        )
        with pytest.raises(ScheduleError, match="duplicate job name"):
            load_jobs(path)

    def test_rejects_an_empty_schedule(self, tmp_path: Path) -> None:
        with pytest.raises(ScheduleError, match="non-empty"):
            load_jobs(write_schedule(tmp_path, "# nothing here\n"))

    @pytest.mark.parametrize("bad", ["30", "30x", "", "m30", "0m"])
    def test_rejects_unparseable_durations(self, tmp_path: Path, bad: str) -> None:
        path = write_schedule(
            tmp_path,
            f'[[jobs]]\nname = "x"\nevery = "{bad}"\nsteps = [["echo", "hi"]]\n',
        )
        with pytest.raises(ScheduleError):
            load_jobs(path)

    @pytest.mark.parametrize("bad", ["25:00", "08:99", "8", "noon"])
    def test_rejects_impossible_clock_times(self, tmp_path: Path, bad: str) -> None:
        path = write_schedule(
            tmp_path,
            f'[[jobs]]\nname = "x"\ndaily_at = "{bad}"\nsteps = [["echo", "hi"]]\n',
        )
        with pytest.raises(ScheduleError):
            load_jobs(path)

    def test_rejects_an_unknown_weekday(self, tmp_path: Path) -> None:
        path = write_schedule(
            tmp_path,
            '[[jobs]]\nname = "x"\nweekly_at = "funday 09:00"\nsteps = [["echo", "hi"]]\n',
        )
        with pytest.raises(ScheduleError, match="unknown day"):
            load_jobs(path)


class TestNextFire:
    def _job(self, tmp_path: Path, trigger_line: str):
        path = write_schedule(
            tmp_path,
            f'[[jobs]]\nname = "x"\n{trigger_line}\ntimeout = "10s"\nsteps = [["echo", "hi"]]\n',
        )
        return load_jobs(path)[0]

    def test_interval_jobs_wait_one_period(self, tmp_path: Path) -> None:
        job = self._job(tmp_path, 'every = "30m"')
        assert seconds_until_next_fire(job, MONDAY_0055_UTC) == 1800

    def test_daily_job_later_today_waits_until_today(self, tmp_path: Path) -> None:
        job = self._job(tmp_path, 'daily_at = "13:00"')
        assert seconds_until_next_fire(job, MONDAY_0055_UTC) == pytest.approx(12 * 3600 + 5 * 60)

    def test_daily_job_already_past_rolls_to_tomorrow(self, tmp_path: Path) -> None:
        job = self._job(tmp_path, 'daily_at = "00:30"')
        assert seconds_until_next_fire(job, MONDAY_0055_UTC) == pytest.approx(23 * 3600 + 35 * 60)

    def test_weekly_job_waits_for_the_right_weekday(self, tmp_path: Path) -> None:
        """From Monday 00:55 UTC, 'sun 14:00' is six days and change away."""
        job = self._job(tmp_path, 'weekly_at = "sun 14:00"')
        expected = (6 * 24 * 3600) + (13 * 3600) + (5 * 60)
        assert seconds_until_next_fire(job, MONDAY_0055_UTC) == pytest.approx(expected)

    def test_weekly_job_on_its_own_day_but_past_the_hour_rolls_a_full_week(
        self, tmp_path: Path
    ) -> None:
        job = self._job(tmp_path, 'weekly_at = "mon 00:30"')
        assert seconds_until_next_fire(job, MONDAY_0055_UTC) == pytest.approx(
            7 * 24 * 3600 - 25 * 60
        )
