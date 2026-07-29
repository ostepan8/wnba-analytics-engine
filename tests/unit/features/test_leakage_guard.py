"""Adversarial tests: steps that deliberately leak, asserted to FAIL.

These are the most valuable tests in the subsystem. Every other test here
proves a feature is computed correctly; these prove that computing it
INCORRECTLY -- in the specific ways DATA_INVENTORY.md and AGENTS.md warn
about -- cannot pass silently.

Each leaky step below is written the way somebody would plausibly write
it in a hurry. `_NaiveLatestJoinStep` in particular is not hypothetical:
it is the exact implementation this package shipped internally before the
per-row as-of join replaced it, and it put July standings on a May game
while passing every as-of check.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import pytest
from feature_fixtures import (
    AS_OF,
    FIRST_TIP,
    TEAM_COLUMNS,
    context,
    frame_of,
    team_row,
    team_schedule,
)

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import (
    LeakageError,
    StepContractError,
    UndeclaredProvenanceError,
)
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import FeatureStep, FilterStep, SourceStep, WindowedStep


def _run(step: object, frame: FeatureFrame, ctx: FeatureContext | None = None) -> FeatureFrame:
    """One step through a real Pipeline, so the guard runs exactly as it
    would in production rather than being invoked directly."""
    return Pipeline(name="adversarial", steps=(step,)).run(  # type: ignore[arg-type]
        frame, context=ctx or context()
    )


# -- the classic: a rolling window that includes the current game -------


class _SelfIncludingRollingStep(WindowedStep):
    """The off-by-one that defines this whole problem: append the current
    row to history BEFORE computing its average, so a team's "last 5
    games" includes the game being predicted.
    """

    @property
    def name(self) -> str:
        return "leaky_rolling"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=("leaky_mean", "leaky_rolling__window_end"),
            window_end_column="leaky_rolling__window_end",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        history: dict[object, list[tuple[datetime, float]]] = {}
        cells: list[Row] = []
        for row in frame.rows:
            key = row["team_id"]
            past = history.setdefault(key, [])
            past.append((row["start_time"], float(row["points_scored"])))  # type: ignore[arg-type]
            window = past[-5:]
            cells.append(
                {
                    "leaky_mean": sum(value for _, value in window) / len(window),
                    "leaky_rolling__window_end": max(at for at, _ in window),
                }
            )
        return tuple(cells)


def test_rolling_window_including_the_current_game_is_rejected() -> None:
    with pytest.raises(LeakageError) as excinfo:
        _run(_SelfIncludingRollingStep(), frame_of(team_schedule()))
    assert "leaky_rolling__window_end" in str(excinfo.value)
    assert "event-time" in str(excinfo.value)


# -- a season aggregate spanning the target date ------------------------


class _WholeSeasonAggregateStep(WindowedStep):
    """`AVG(points) GROUP BY team, season` -- the aggregate that reads
    perfectly in SQL and folds every later game of the season, including
    the one being predicted, into its own feature.
    """

    @property
    def name(self) -> str:
        return "leaky_season_avg"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=("season_points_avg", "leaky_season_avg__window_end"),
            window_end_column="leaky_season_avg__window_end",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        totals: dict[object, list[float]] = {}
        latest: dict[object, datetime] = {}
        for row in frame.rows:
            key = (row["team_id"], row["season"])
            totals.setdefault(key, []).append(float(row["points_scored"]))  # type: ignore[arg-type]
            latest[key] = max(latest.get(key, row["start_time"]), row["start_time"])  # type: ignore[type-var]
        return tuple(
            {
                "season_points_avg": sum(totals[(row["team_id"], row["season"])])
                / len(totals[(row["team_id"], row["season"])]),
                "leaky_season_avg__window_end": latest[(row["team_id"], row["season"])],
            }
            for row in frame.rows
        )


def test_season_aggregate_spanning_the_target_game_is_rejected() -> None:
    with pytest.raises(LeakageError):
        _run(_WholeSeasonAggregateStep(), frame_of(team_schedule()))


# -- the standings trap, both halves ------------------------------------


class _NaiveLatestJoinStep(FeatureStep):
    """Join "the newest standings snapshot at or before as_of" onto every
    row. Every value really is from before the boundary, so an as-of-only
    guard passes it -- and a game played in May gets July's record.
    """

    @property
    def name(self) -> str:
        return "naive_latest_standings"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.JOIN,
            adds_columns=("standings_wins", "standings_captured_at"),
            as_of_columns=("standings_captured_at",),
        )

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        captured_at = context.as_of - timedelta(days=1)
        cells = tuple(
            {"standings_wins": 18, "standings_captured_at": captured_at} for _ in frame.rows
        )
        return frame.merge_cells(cells, self.provenance.adds_columns).declaring(
            as_of_columns=("standings_captured_at",),
            window_end_columns=("standings_captured_at",),
        )


def test_latest_snapshot_joined_onto_every_row_is_rejected() -> None:
    """The bug this package actually had. The snapshot precedes as_of and
    still postdates the games it is attached to.
    """
    with pytest.raises(LeakageError) as excinfo:
        _run(_NaiveLatestJoinStep(), frame_of(team_schedule()))
    assert "standings_captured_at" in str(excinfo.value)


def test_reading_team_standings_is_refused_before_any_query_runs() -> None:
    """team_standings is a current-state upsert; reading it for a 2023
    game returns 2026 standings (db/migrations/0013_standings.sql).
    Refused at the SQL, so no connection is even touched -- hence the
    None connection below.
    """
    from wnba_engine.repositories import feature_repo

    with pytest.raises(feature_repo.ForbiddenSourceError) as excinfo:
        feature_repo.execute_point_in_time(
            None,  # type: ignore[arg-type]
            "SELECT wins FROM team_standings WHERE season = 2023 AND %(as_of)s IS NOT NULL",
            {"as_of": AS_OF},
        )
    assert "current-state" in str(excinfo.value).lower()


def test_team_standings_history_is_not_caught_by_the_team_standings_rule() -> None:
    """The append-only companion must stay readable -- a word-boundary
    match that also blocked it would push callers back to the bad table.
    """
    from wnba_engine.repositories import feature_repo

    sql = "SELECT wins FROM team_standings_history WHERE captured_at <= %(as_of)s"
    # AttributeError, not ForbiddenSourceError: the scan let it through and
    # the call then died on the None connection, which is the proof wanted.
    with pytest.raises(AttributeError):
        feature_repo.execute_point_in_time(None, sql, {"as_of": AS_OF})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT award FROM season_awards WHERE %(as_of)s IS NOT NULL", "ground truth"),
        ("SELECT age FROM players WHERE %(as_of)s IS NOT NULL", "mutable snapshot"),
        ("SELECT jersey_number FROM players WHERE %(as_of)s IS NOT NULL", "mutable"),
    ],
)
def test_known_leaky_columns_are_refused(sql: str, expected: str) -> None:
    from wnba_engine.repositories import feature_repo

    with pytest.raises(feature_repo.ForbiddenSourceError) as excinfo:
        feature_repo.execute_point_in_time(None, sql, {"as_of": AS_OF})  # type: ignore[arg-type]
    assert expected in str(excinfo.value)


def test_query_without_an_as_of_filter_is_refused() -> None:
    """An unbounded read returns plausible rows and is still a leak."""
    from wnba_engine.repositories import feature_repo

    with pytest.raises(feature_repo.ForbiddenSourceError) as excinfo:
        feature_repo.execute_point_in_time(
            None,  # type: ignore[arg-type]
            "SELECT id FROM games WHERE status = 'final'",
            {"as_of": AS_OF},
        )
    assert "as_of" in str(excinfo.value)


def test_time_invariant_query_still_refuses_mutable_columns() -> None:
    """execute_time_invariant drops the as-of requirement, not the scan."""
    from wnba_engine.repositories import feature_repo

    with pytest.raises(feature_repo.ForbiddenSourceError):
        feature_repo.execute_time_invariant(
            None,  # type: ignore[arg-type]
            "SELECT id, age FROM players",
            {},
            justification="height and weight do not change",
        )


def test_time_invariant_query_demands_a_written_justification() -> None:
    from wnba_engine.repositories import feature_repo

    with pytest.raises(feature_repo.ForbiddenSourceError):
        feature_repo.execute_time_invariant(
            None,  # type: ignore[arg-type]
            "SELECT id, height FROM players",
            {},
            justification="   ",
        )


# -- rows from beyond the boundary --------------------------------------


class _FutureRowsSourceStep(SourceStep):
    """A loader that forgot its WHERE clause."""

    @property
    def name(self) -> str:
        return "future_loader"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.SOURCE,
            adds_columns=TEAM_COLUMNS,
            as_of_columns=("start_time",),
            event_time_column="start_time",
        )

    def fetch(self, context: FeatureContext) -> tuple[Row, ...]:
        return (
            team_row(game_id=1, team_id=1, start_time=FIRST_TIP),
            team_row(game_id=2, team_id=1, start_time=context.as_of + timedelta(days=1)),
        )


def test_rows_after_the_boundary_are_rejected() -> None:
    with pytest.raises(LeakageError) as excinfo:
        _run(_FutureRowsSourceStep(), FeatureFrame.empty())
    assert "as-of" in str(excinfo.value)


# -- a step that cannot say where its data came from --------------------


class _AnonymousSourceStep(FeatureStep):
    """Emits rows with no as-of declaration at all. The cheapest way to
    defeat a timestamp check is to publish no timestamp; that is why
    silence is treated as failure rather than as absence of evidence.
    """

    @property
    def name(self) -> str:
        return "anonymous"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.SOURCE,
            adds_columns=("a", "b"),
            as_of_columns=("a",),
            event_time_column="a",
        )

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        # Declares provenance correctly and then emits a frame that carries
        # none of it -- the declaration is not what the guard trusts.
        return FeatureFrame.from_rows([{"a": 1, "b": 2}], columns=("a", "b"))


def test_rows_with_no_declared_provenance_are_rejected() -> None:
    with pytest.raises(UndeclaredProvenanceError):
        _run(_AnonymousSourceStep(), FeatureFrame.empty())


def test_naive_timestamps_in_an_anchor_are_rejected() -> None:
    """Every column this reads is TIMESTAMPTZ, so a naive value means the
    zone was stripped somewhere -- and a naive comparison is how an "it
    passed locally" leak happens.
    """
    naive = datetime(2025, 6, 1, 23, 0)  # noqa: DTZ001 -- the point of the test
    rows = [team_row(game_id=1, team_id=1, start_time=FIRST_TIP) | {"start_time": naive}]
    frame = FeatureFrame.from_rows(
        rows, columns=TEAM_COLUMNS, as_of_columns=("start_time",), event_time_column="start_time"
    )

    class _Passthrough(FeatureStep):
        @property
        def name(self) -> str:
            return "passthrough"

        @property
        def provenance(self) -> StepProvenance:
            return StepProvenance(kind=StepKind.ROW_LOCAL)

        def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
            return frame

    with pytest.raises(StepContractError) as excinfo:
        _run(_Passthrough(), frame)
    assert "naive" in str(excinfo.value)


# -- structural contract violations -------------------------------------


class _UndeclaredColumnStep(FeatureStep):
    @property
    def name(self) -> str:
        return "sneaky_column"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=("declared",))

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        cells = tuple({"declared": 1, "undeclared": 2} for _ in frame.rows)
        return frame.merge_cells(cells, ("declared", "undeclared"))


def test_a_step_may_not_add_a_column_it_did_not_declare() -> None:
    """A step that can add a column unnoticed can add a leaky one."""
    with pytest.raises(StepContractError) as excinfo:
        _run(_UndeclaredColumnStep(), frame_of(team_schedule(count=2)))
    assert "undeclared" in str(excinfo.value)


class _RowInventingFilterStep(FilterStep):
    @property
    def name(self) -> str:
        return "inventing_filter"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        return True

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        return frame.with_rows([*frame.rows, frame.rows[0]])


def test_a_filter_may_not_add_rows() -> None:
    with pytest.raises(StepContractError):
        _run(_RowInventingFilterStep(), frame_of(team_schedule(count=2)))


class _RowDroppingMapStep(FeatureStep):
    @property
    def name(self) -> str:
        return "dropping_map"

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=("x",))

    def apply(self, frame: FeatureFrame, context: FeatureContext) -> FeatureFrame:
        trimmed = frame.with_rows(frame.rows[:1])
        return trimmed.merge_cells(tuple({"x": 1} for _ in trimmed.rows), ("x",))


def test_a_row_local_step_may_not_change_the_row_count() -> None:
    with pytest.raises(StepContractError):
        _run(_RowDroppingMapStep(), frame_of(team_schedule(count=3)))


# -- declarations that cannot even be constructed -----------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        # windowed with no window end: unverifiable by construction
        {"kind": StepKind.WINDOWED, "adds_columns": ("x",)},
        # source with no as-of anchor
        {"kind": StepKind.SOURCE, "adds_columns": ("x",), "event_time_column": "x"},
        # join with no as-of anchor
        {"kind": StepKind.JOIN, "adds_columns": ("x",)},
        # derived column claiming independent provenance
        {"kind": StepKind.ROW_LOCAL, "adds_columns": ("x",), "as_of_columns": ("x",)},
        # unanchored data with no written reason
        {"kind": StepKind.TIME_INVARIANT, "adds_columns": ("x",)},
        # a filter that also adds columns
        {"kind": StepKind.FILTER, "adds_columns": ("x",)},
    ],
)
def test_ill_formed_declarations_fail_at_construction(kwargs: Mapping[str, object]) -> None:
    """Strategies are composed at import time, so a mis-declared step is
    an ImportError rather than a surprise mid-backfill.
    """
    with pytest.raises(ValueError):
        StepProvenance(**kwargs)  # type: ignore[arg-type]


def test_window_end_column_must_be_declared_as_a_column() -> None:
    with pytest.raises(ValueError):
        StepProvenance(
            kind=StepKind.WINDOWED, adds_columns=("x",), window_end_column="somewhere_else"
        )


# -- the guard does not fire on correct work ----------------------------


def test_a_correct_backward_window_passes() -> None:
    from wnba_engine.features.steps.derivation import RollingMeanStep

    frame = _run(
        RollingMeanStep(value_columns=("points_scored",), window=3, label="form"),
        frame_of(team_schedule(count=5)),
    )
    ends: Sequence[object] = [row["form__window_end"] for row in frame.rows]
    assert ends[0] is None
    assert all(
        end < row["start_time"]  # type: ignore[operator]
        for end, row in zip(ends[1:], frame.rows[1:], strict=True)
    )
    assert frame.rows[0]["points_scored_mean_3"] is None
