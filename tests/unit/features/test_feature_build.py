"""Materialisation helpers: CSV export and the preview renderer."""

from __future__ import annotations

import csv
from pathlib import Path

from feature_fixtures import frame_of, team_schedule

from wnba_engine.pipeline.feature_build import preview, write_csv


def test_csv_export_keeps_the_declared_column_order(tmp_path: Path) -> None:
    frame = frame_of(team_schedule(count=3))
    path = tmp_path / "nested" / "features.csv"
    write_csv(frame, path)

    with path.open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == list(frame.columns)
    assert len(rows) == 4


def test_csv_export_writes_timestamps_as_iso_8601(tmp_path: Path) -> None:
    """A materialised frame that lost its anchors could never be
    re-guarded, so they have to survive the round trip legibly.
    """
    frame = frame_of(team_schedule(count=1))
    path = tmp_path / "features.csv"
    write_csv(frame, path)

    with path.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["start_time"] == frame.rows[0]["start_time"].isoformat()  # type: ignore[union-attr]


def test_preview_skips_columns_the_frame_does_not_have() -> None:
    frame = frame_of(team_schedule(count=2))
    lines = preview(frame, ["game_id", "not_a_column", "points_scored"], count=1)
    assert len(lines) == 1
    assert "not_a_column" not in lines[0]
    assert "game_id=1" in lines[0]
