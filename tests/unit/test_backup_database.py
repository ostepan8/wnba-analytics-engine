"""Backup rotation, which is the half of a backup that can destroy data.

Taking a dump is hard to get subtly wrong -- pg_dump either produces a file or
returns non-zero. Deleting old ones is the dangerous part, and the specific
danger is deleting a good dump in favour of a broken newer one: a dump killed
partway through leaves a truncated file that is indistinguishable from a valid
one to anything merely listing the directory.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wnba_engine.backup import database
from wnba_engine.backup.database import back_up_database

URL = "postgresql://wnba:secret@127.0.0.1:5434/wnba_engine"


def fake_pg_dump(*, exit_code: int = 0, stderr: bytes = b"", payload: bytes = b"DUMP"):
    """Stand in for pg_dump, writing to whatever --file it was handed."""

    def _run(command, **kwargs):
        del kwargs
        if exit_code == 0:
            target = Path(command[command.index("--file") + 1])
            target.write_bytes(payload)
        return subprocess.CompletedProcess(command, exit_code, b"", stderr)

    return _run


def seed_old_dumps(directory: Path, count: int) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for day in range(1, count + 1):
        path = directory / f"wnba_engine-202608{day:02d}T060000Z.dump"
        path.write_bytes(b"old")
        paths.append(path)
    return paths


def test_a_dump_is_written(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", fake_pg_dump())
    result = back_up_database(URL, directory=tmp_path, keep=14)

    assert result.path.exists()
    assert result.path.read_bytes() == b"DUMP"
    assert result.size_bytes == 4


def test_the_directory_is_created_if_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", fake_pg_dump())
    target = tmp_path / "nested" / "backups"
    result = back_up_database(URL, directory=target, keep=14)
    assert result.path.parent == target


def test_only_the_newest_dumps_are_kept(tmp_path, monkeypatch) -> None:
    old = seed_old_dumps(tmp_path, 5)
    monkeypatch.setattr(subprocess, "run", fake_pg_dump())

    result = back_up_database(URL, directory=tmp_path, keep=3)

    remaining = sorted(p.name for p in tmp_path.glob("*.dump"))
    assert len(remaining) == 3
    assert result.path.name in remaining
    # Oldest go first.
    assert old[0].name not in remaining
    assert old[1].name not in remaining


def test_nothing_is_pruned_when_under_the_limit(tmp_path, monkeypatch) -> None:
    seed_old_dumps(tmp_path, 2)
    monkeypatch.setattr(subprocess, "run", fake_pg_dump())

    result = back_up_database(URL, directory=tmp_path, keep=14)

    assert result.pruned == ()
    assert len(list(tmp_path.glob("*.dump"))) == 3


def test_a_failed_dump_raises_and_deletes_nothing(tmp_path, monkeypatch) -> None:
    """The critical case. If a failing dump still pruned, a run of failures would
    quietly consume the entire backup history while reporting only that today's
    dump failed."""
    existing = seed_old_dumps(tmp_path, 5)
    monkeypatch.setattr(subprocess, "run", fake_pg_dump(exit_code=1, stderr=b"connection refused"))

    with pytest.raises(RuntimeError, match="connection refused"):
        back_up_database(URL, directory=tmp_path, keep=1)

    assert all(path.exists() for path in existing)


def test_a_failed_dump_leaves_no_partial_file_behind(tmp_path, monkeypatch) -> None:
    """A truncated dump left in place looks valid to the pruner, which would then
    happily delete a good one to make room for it."""
    monkeypatch.setattr(subprocess, "run", fake_pg_dump(exit_code=1))

    with pytest.raises(RuntimeError):
        back_up_database(URL, directory=tmp_path, keep=14)

    assert list(tmp_path.iterdir()) == []


def test_a_timeout_raises_rather_than_reporting_success(tmp_path, monkeypatch) -> None:
    def _timeout(command, **kwargs):
        del kwargs
        raise subprocess.TimeoutExpired(command, database.DUMP_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        back_up_database(URL, directory=tmp_path, keep=14)


def test_the_password_is_not_passed_on_the_command_line(tmp_path, monkeypatch) -> None:
    """argv is world-readable through /proc. The connection string carries the
    password, so it is the last argument to pg_dump and nowhere else -- but it
    must never be split into a --password flag or logged."""
    seen: list[str] = []

    def _capture(command, **kwargs):
        del kwargs
        seen[:] = command
        target = Path(command[command.index("--file") + 1])
        target.write_bytes(b"DUMP")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _capture)
    back_up_database(URL, directory=tmp_path, keep=14)

    assert "--password" not in seen
    assert not any(arg == "secret" for arg in seen)


def test_filenames_sort_chronologically() -> None:
    """Pruning relies on lexical order being time order, so the format is fixed
    width and UTC -- a local-time or variable-width name would prune the wrong
    file exactly once a year."""
    earlier = database._filename(datetime(2026, 8, 9, 6, 0, tzinfo=UTC))
    later = database._filename(datetime(2026, 8, 10, 6, 0, tzinfo=UTC))
    assert earlier < later
    assert len(earlier) == len(later)
