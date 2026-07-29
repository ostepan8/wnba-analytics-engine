"""Orchestration for a feature build: connection -> strategy -> frame.

Mirrors the other pipeline modules -- a function that owns the connection
lifecycle and returns a frozen result dataclass the CLI can echo -- with
one addition: the connection is put into READ ONLY mode first.

That is not decoration. Every other pipeline module in this package
writes; this one must not, and `SET TRANSACTION READ ONLY` turns "the
feature layer is read-only" from a property of the code as currently
written into one Postgres enforces. A step that grew a write would fail
here rather than in production.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wnba_engine.db.pool import Database
from wnba_engine.features import strategies
from wnba_engine.features.context import FeatureContext
from wnba_engine.features.frame import FeatureFrame
from wnba_engine.features.source import DEFAULT_BOX_SCORE_SOURCE, PostgresRowSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FeatureBuildResult:
    """Summary of one build, shaped for `click.echo` like the ingest results.

    Deliberately carries no rows: this gets printed, and a 2,700-row frame
    in a terminal is not a report.
    """

    strategy: str
    as_of: str
    seasons: tuple[int, ...]
    season_types: tuple[str, ...]
    steps_applied: int
    rows: int
    columns: int
    written_to: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureBuild:
    """The frame plus its summary. Separate fields so a caller can hand
    the summary to a log or a CLI without dragging the data along.
    """

    frame: FeatureFrame
    result: FeatureBuildResult


def build_features(
    db: Database,
    *,
    strategy: str,
    context: FeatureContext,
    box_score_source: str = DEFAULT_BOX_SCORE_SOURCE,
    output_path: Path | None = None,
) -> FeatureBuild:
    """Run a named strategy at one point-in-time boundary.

    The whole build happens inside ONE connection, so every loader and
    join reads the same snapshot. With the 2-hourly ingestion jobs
    running, splitting the reads across connections could put a standings
    snapshot in the frame that did not exist when the games were read --
    a leak measured in minutes, but a leak.
    """
    with db.connection() as conn:
        conn.read_only = True
        source = PostgresRowSource(conn, box_score_source=box_score_source)
        pipeline = strategies.build(strategy, source)
        frame = pipeline.run(context=context)

    written = None
    if output_path is not None:
        write_csv(frame, output_path)
        written = str(output_path)

    logger.info(
        "built %s: %d row(s), %d column(s), %s",
        strategy,
        len(frame),
        len(frame.columns),
        context.describe(),
    )
    return FeatureBuild(
        frame=frame,
        result=FeatureBuildResult(
            strategy=pipeline.name,
            as_of=context.as_of.isoformat(),
            seasons=context.seasons,
            season_types=context.season_types,
            steps_applied=len(pipeline.steps),
            rows=len(frame),
            columns=len(frame.columns),
            written_to=written,
        ),
    )


def write_csv(frame: FeatureFrame, path: Path) -> None:
    """Materialise a frame to CSV.

    CSV rather than Parquet for the same reason this package avoids
    pandas: it is stdlib, and the frames are small. Timestamps go out as
    ISO-8601 so the as-of anchors survive the round trip legibly -- a
    materialised frame that loses its anchors could never be re-guarded.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(frame.columns)
        for row in frame.rows:
            writer.writerow(_render(row.get(column)) for column in frame.columns)


def _render(value: object) -> object:
    return value.isoformat() if isinstance(value, datetime) else value


def preview(frame: FeatureFrame, columns: Sequence[str], count: int = 5) -> tuple[str, ...]:
    """A few rows, projected to `columns`, for eyeballing a build."""
    available = [column for column in columns if column in frame.column_set]
    return tuple(
        ", ".join(f"{column}={row.get(column)!r}" for column in available)
        for row in frame.head(count)
    )
