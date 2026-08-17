"""Nightly logical backups of the engine database.

**This is not an off-site backup, and should not be mistaken for one.** The
dumps land on the same host and the same disk as the database they came from,
so they do not survive losing that machine. What they do protect against is the
more likely failure: a bad migration, an accidental DELETE, a corrupted table, a
parser that wrote wrong rows for a week. Those are recoverable from a dump on
the same disk and are not recoverable without one.

`pg_dump -Fc` rather than plain SQL: it is compressed (the ~1.7 GB database
dumps to ~140 MB), and pg_restore can select individual tables out of it, which
is what "undo the last ingest" actually needs.

The dump runs against the live database with no lock held on writers -- pg_dump
takes a consistent snapshot -- so it is safe to run while the scheduler works.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# The dump is a network-free local operation but a large one; a database that
# has grown well past today's ~1.7 GB should still finish inside this.
DUMP_TIMEOUT_SECONDS = 3600

FILENAME_PREFIX = "wnba_engine-"
FILENAME_SUFFIX = ".dump"


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    size_bytes: int
    pruned: tuple[Path, ...]

    def __str__(self) -> str:
        pruned = f", pruned {len(self.pruned)}" if self.pruned else ""
        return f"{self.path.name} ({self.size_bytes / 1_048_576:.1f} MiB){pruned}"


def back_up_database(database_url: str, *, directory: Path, keep: int) -> BackupResult:
    """Dump the database and prune old dumps. Raises on a failed dump."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / _filename(datetime.now(UTC))

    # Write to a temporary name and rename on success. A dump interrupted
    # halfway is a truncated file that looks exactly like a valid one to
    # anything listing the directory -- including the pruning below, which
    # would happily delete a good dump in favour of a broken newer one.
    partial = target.with_suffix(target.suffix + ".partial")
    _run_pg_dump(database_url, partial)
    partial.rename(target)

    pruned = _prune(directory, keep=keep, newest=target)
    result = BackupResult(path=target, size_bytes=target.stat().st_size, pruned=pruned)
    logger.info("database backup: %s", result)
    return result


def _run_pg_dump(database_url: str, target: Path) -> None:
    # The URL carries the password, so it goes in the environment rather than
    # argv -- argv is world-readable via /proc on a shared host.
    env = {**os.environ, "PGCONNECT_TIMEOUT": "10"}
    command = [
        "pg_dump",
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(target),
        database_url,
    ]
    try:
        completed = subprocess.run(
            command, env=env, capture_output=True, timeout=DUMP_TIMEOUT_SECONDS, check=False
        )
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump timed out after {DUMP_TIMEOUT_SECONDS}s") from exc

    if completed.returncode != 0:
        target.unlink(missing_ok=True)
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"pg_dump failed (exit {completed.returncode}): {stderr}")


def _prune(directory: Path, *, keep: int, newest: Path) -> tuple[Path, ...]:
    """Keep the `keep` most recent dumps. Filenames sort chronologically."""
    dumps = sorted(
        (p for p in directory.glob(f"{FILENAME_PREFIX}*{FILENAME_SUFFIX}") if p.is_file()),
        reverse=True,
    )
    stale = [p for p in dumps[max(keep, 1):] if p != newest]
    for path in stale:
        path.unlink(missing_ok=True)
    return tuple(stale)


def _filename(moment: datetime) -> str:
    """UTC, second precision, fixed width -- so lexical order is time order."""
    return f"{FILENAME_PREFIX}{moment:%Y%m%dT%H%M%SZ}{FILENAME_SUFFIX}"
