"""Entry point for the scheduler service: `python -m wnba_engine.scheduler`.

Runs in the foreground and logs to stdout, which is what a container and a
systemd unit both want -- journald captures it, and there is no log file to
rotate or forget about.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from wnba_engine.config import load_settings
from wnba_engine.db.pool import Database
from wnba_engine.scheduler.config import ScheduleError, load_jobs
from wnba_engine.scheduler.runner import run_forever

DEFAULT_SCHEDULE_PATH = Path(__file__).resolve().parents[2] / "deploy" / "schedule.toml"

logger = logging.getLogger("wnba_engine.scheduler")


def main() -> int:
    _configure_logging()
    schedule_path = Path(os.environ.get("WNBA_SCHEDULE_PATH", DEFAULT_SCHEDULE_PATH))

    try:
        jobs = load_jobs(schedule_path)
    except ScheduleError as exc:
        # Fatal on purpose. A schedule we cannot parse means we do not know what
        # is supposed to run, and starting anyway would recreate exactly the
        # "looks alive, does nothing" state this service exists to prevent.
        logger.error("refusing to start: %s", exc)
        return 2

    db = Database(load_settings().database_url)
    try:
        asyncio.run(run_forever(jobs, db))
    except KeyboardInterrupt:
        logger.info("scheduler stopped")
    finally:
        db.close()
    return 0


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("WNBA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    # httpx logs every request URL at INFO, including the-odds-api's `apiKey=`
    # query parameter in cleartext. Our own client redacts it; httpx's logger is
    # a separate path that bypasses that. Same suppression as the CLI.
    logging.getLogger("httpx").setLevel(logging.WARNING)


if __name__ == "__main__":
    raise SystemExit(main())
