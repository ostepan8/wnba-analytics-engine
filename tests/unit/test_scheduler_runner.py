"""How a job run settles, which is the part the health view reports on.

Three distinctions matter and all three are easy to get wrong:

  * a failing step must stop the run, not the process -- one bad API key must
    not take the healthy jobs down with it;
  * a later step must not run after an earlier one failed, because the steps in
    every real job are ordered dependencies (log-divergences reads tables that
    refresh-venue-prices fills);
  * a timeout must be distinguishable from a failure, since they call for
    different fixes.
"""

from __future__ import annotations

import sys

import pytest

from wnba_engine.scheduler.config import Job, Trigger
from wnba_engine.scheduler.runner import _run_steps

PYTHON = sys.executable


def job(*steps: tuple[str, ...], timeout: int = 30) -> Job:
    return Job(
        name="test-job",
        trigger=Trigger(every_seconds=3600),
        steps=steps,
        timeout_seconds=timeout,
        run_at_start=False,
        description="",
    )


def python_step(code: str) -> tuple[str, ...]:
    return (PYTHON, "-c", code)


class TestRunSteps:
    async def test_all_steps_succeeding_reports_ok(self) -> None:
        exit_code, error = await _run_steps(
            job(python_step("print('one')"), python_step("print('two')"))
        )
        assert (exit_code, error) == (0, None)

    async def test_a_failing_step_stops_the_run(self, tmp_path) -> None:
        """The marker file proves the second step never ran. Steps are ordered
        dependencies, so continuing past a failure would run commands against
        state their predecessor was supposed to produce."""
        marker = tmp_path / "second-step-ran"
        exit_code, error = await _run_steps(
            job(
                python_step("raise SystemExit(3)"),
                python_step(f"open({str(marker)!r}, 'w').close()"),
            )
        )
        assert exit_code == 3
        assert error is not None and "exit 3" in error
        assert not marker.exists()

    async def test_failure_returns_rather_than_raises(self) -> None:
        """_run_steps never propagates: the scheduler has to stay up through a
        provider outage and record it, not die and take five other jobs along."""
        exit_code, _ = await _run_steps(job(python_step("raise SystemExit(1)")))
        assert exit_code == 1

    async def test_stderr_is_captured_with_the_failure(self) -> None:
        exit_code, error = await _run_steps(
            job(
                python_step(
                    "import sys; print('boom detail', file=sys.stderr); raise SystemExit(1)"
                )
            )
        )
        assert exit_code == 1
        assert error is not None and "boom detail" in error

    async def test_a_timeout_is_reported_as_none_not_as_a_failure(self) -> None:
        """None distinguishes 'we killed it' from 'it returned an error', which
        the runner maps to status 'timeout' rather than 'failed'."""
        exit_code, error = await _run_steps(
            job(python_step("import time; time.sleep(30)"), timeout=1)
        )
        assert exit_code is None
        assert error is not None and "timed out" in error

    async def test_the_timeout_is_a_budget_across_all_steps(self) -> None:
        """Not per-step: a job of five slow steps must not quietly get five
        times the timeout it declared."""
        exit_code, error = await _run_steps(
            job(
                python_step("import time; time.sleep(2)"),
                python_step("import time; time.sleep(30)"),
                timeout=3,
            )
        )
        assert exit_code is None
        assert error is not None and "timed out" in error

    async def test_a_missing_executable_surfaces_rather_than_hanging(self) -> None:
        with pytest.raises(FileNotFoundError):
            await _run_steps(job(("wnba-engine-that-does-not-exist",)))
