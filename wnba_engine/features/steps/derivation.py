"""Situational features -- the ones ROADMAP.md Phase 1/2 names explicitly:
home/road, rest days, back-to-backs, pace, and rolling form.

Every cross-row derivation here is a WindowedStep, which means it is
obliged to publish the last instant its window consumed and the guard
asserts that instant is strictly before the row's own tip-off. That is
the difference between "the window is backward-looking" as a comment and
as a test that runs on every build.

One timezone decision worth knowing about. `games.start_time` is
TIMESTAMPTZ stored in UTC, and a WNBA evening tip-off lands on the NEXT
UTC date -- the earliest game in this database reads 2022-04-24 01:00 UTC
and was played on the evening of April 23 locally. Defining a
back-to-back as "consecutive UTC dates" would therefore be wrong for most
of the schedule, and converting to Eastern would import a tz database
dependency for a definition that is fuzzy anyway (the league plays across
four US time zones). So rest is measured in ELAPSED HOURS between
tip-offs, and a back-to-back is any gap under 36 hours -- which captures
consecutive-evening games regardless of which zone either was played in,
and cannot be thrown off by a date boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import RowMapStep, WindowedStep
from wnba_engine.features.steps._windowing import (
    WINDOW_COUNT_SUFFIX,
    WINDOW_END_SUFFIX,
    chronological,
    event_time,
    finalise,
    mean_of,
    numeric,
    trailing_walk,
)

#: A gap shorter than this counts as a back-to-back. 36h is the widest gap
#: two consecutive-evening games can have (an early game followed by a
#: late one three zones west) and comfortably narrower than the ~48h a
#: genuine one-day-off pairing produces.
BACK_TO_BACK_MAX_GAP = timedelta(hours=36)

#: Columns describing the OUTCOME of the row's own game. They are inputs
#: to the backward-looking steps below (a rolling form average needs past
#: results) and must never be fed to a model as features FOR that row --
#: they are what the row is trying to predict. Named here so a caller can
#: drop them in one line before training.
TARGET_COLUMNS: tuple[str, ...] = ("points_scored", "points_allowed", "point_margin", "won")


@dataclass(frozen=True, slots=True)
class HomeAwayStep(RowMapStep):
    """`is_home` (bool, from the loader) -> a categorical label.

    Exists so the encoding layer has a string column to one-hot, and so
    the home/road split ROADMAP.md asks for is addressable by name rather
    than by remembering which way the boolean points.
    """

    step_name: str = "home_away"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=("home_away",))

    def transform(self, row: Row, context: FeatureContext) -> Row:
        is_home = row.get("is_home")
        if is_home is None:
            return {"home_away": None}
        return {"home_away": "home" if is_home else "away"}


@dataclass(frozen=True, slots=True)
class GameOutcomeStep(RowMapStep):
    """Margin and win flag for the row's OWN game -- targets, not features.

    See TARGET_COLUMNS. They live in the frame because the rolling and
    season-to-date steps need each team's PAST results, and the only place
    a past result exists is on that past game's own row.
    """

    step_name: str = "game_outcome"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=("point_margin", "won"))

    def transform(self, row: Row, context: FeatureContext) -> Row:
        scored, allowed = row.get("points_scored"), row.get("points_allowed")
        if scored is None or allowed is None:
            return {"point_margin": None, "won": None}
        margin = int(scored) - int(allowed)
        return {"point_margin": margin, "won": margin > 0}


@dataclass(frozen=True, slots=True)
class RestDaysStep(WindowedStep):
    """Days since this team's previous game, and the back-to-back flag.

    Grouped by `group_by` -- team_id for a team-grain frame, and team_id
    for a player-grain one too: a player's rest IS their team's schedule,
    and grouping by player_id would hand a player who sat out a game a
    fictitious extra day of rest.

    That player-grain case is why this step tracks the previous DISTINCT
    event time rather than simply the previous row. A player-grain frame
    has ~12 rows sharing one (team, tip-off); treating a sibling row as
    "the previous game" would report zero rest and publish a window end
    equal to the row's own event time, which the guard would (correctly)
    reject as a leak.
    """

    group_by: tuple[str, ...] = ("team_id",)
    step_name: str = "rest_days"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                f"{self.step_name}{WINDOW_END_SUFFIX}",
                "rest_days",
                "is_back_to_back",
            ),
            window_end_column=f"{self.step_name}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        self._require_columns(frame, self.group_by)
        window_end_column = f"{self.step_name}{WINDOW_END_SUFFIX}"
        cells: list[Row | None] = [None] * len(frame.rows)
        # key -> (previous distinct event time, current distinct event time)
        seen: dict[tuple[object, ...], tuple[datetime | None, datetime]] = {}

        for index, row in chronological(frame, self.name):
            key = tuple(row.get(column) for column in self.group_by)
            event_at = event_time(frame, row, self.name)
            prior, current = seen.get(key, (None, event_at))
            if current != event_at:
                prior, current = current, event_at
            seen[key] = (prior, current)
            if prior is None:
                cells[index] = {
                    window_end_column: None,
                    "rest_days": None,
                    "is_back_to_back": False,
                }
            else:
                gap = event_at - prior
                cells[index] = {
                    window_end_column: prior,
                    "rest_days": gap.total_seconds() / 86_400.0,
                    "is_back_to_back": gap < BACK_TO_BACK_MAX_GAP,
                }
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class RollingMeanStep(WindowedStep):
    """Mean of the previous N observations, STRICTLY excluding this row.

    The exclusion is the entire point and is enforced by construction: a
    row is appended to its group's history only AFTER its own cells are
    computed, so there is no ordering of the loop in which a row can see
    itself. The published window end is the tip-off of the most recent
    contributing game, which the guard then compares to this row's own.

    Nulls are skipped rather than treated as zero (`pace` is null for any
    game with no balldontlie advanced-stats row), so `<label>__window_games`
    reports how many observations actually contributed -- a "5-game
    average" over 2 games is a different number and should be legible as
    one.
    """

    value_columns: tuple[str, ...]
    window: int
    group_by: tuple[str, ...] = ("team_id",)
    label: str = "rolling"

    def __post_init__(self) -> None:
        if self.window < 1:
            raise StepContractError(f"rolling window must be >= 1, got {self.window}")
        if not self.value_columns:
            raise StepContractError("rolling step needs at least one value column")

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{column}_mean_{self.window}" for column in self.value_columns)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                *self.output_columns,
                f"{self.label}{WINDOW_COUNT_SUFFIX}",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(frame, (*self.group_by, *self.value_columns))
        window_end_column = f"{self.label}{WINDOW_END_SUFFIX}"
        count_column = f"{self.label}{WINDOW_COUNT_SUFFIX}"
        cells: list[Row | None] = [None] * len(frame.rows)

        # trailing_walk holds each row's observation until the walk
        # reaches a STRICTLY later event time, which is what this loop
        # used to do only for "the previous row" -- it appended after
        # emitting, so a row sharing an instant with an earlier one still
        # saw it. That is not theoretical: player 137 has box-score rows
        # in two games tipping off simultaneously (2024-08-23T23:30Z), and
        # the per-player window here published a window end equal to the
        # row's own tip-off, which the guard rejected. See _windowing.
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=self.group_by,
            observe=lambda row: {column: row.get(column) for column in self.value_columns},
        ):
            contributing = past[-self.window :]
            cell: dict[str, object] = {
                output: mean_of(numeric(contributing, column))
                for column, output in zip(self.value_columns, self.output_columns, strict=True)
            }
            cell[count_column] = len(contributing)
            cell[window_end_column] = max((at for at, _ in contributing), default=None)
            cells[index] = cell
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class SeasonToDateStep(WindowedStep):
    """Record and scoring so far THIS SEASON, excluding the current game.

    The counterpart to the classic season-aggregate leak: reading
    `team_standings` (or any full-season SUM) for a mid-season game folds
    that game's own result -- and the rest of the season's -- into its own
    features. Here the accumulator is keyed by (group, season) and, like
    the rolling step, is updated only after the current row is emitted.
    """

    group_by: tuple[str, ...] = ("team_id",)
    season_column: str = "season"
    label: str = "season_to_date"

    @property
    def name(self) -> str:
        return self.label

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(
                "season_games_prior",
                "season_wins_prior",
                "season_win_pct_prior",
                f"{self.label}{WINDOW_END_SUFFIX}",
            ),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(frame, (*self.group_by, self.season_column, "won"))
        window_end_column = f"{self.label}{WINDOW_END_SUFFIX}"
        cells: list[Row | None] = [None] * len(frame.rows)

        # Counters replaced by trailing_walk for the same reason as the
        # rolling step above: an accumulator updated after each row still
        # counts a SIMULTANEOUS earlier row. The list this walks is at
        # most one season of games per key, so recomputing the two sums
        # per row is a few thousand additions on the largest frame here.
        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=(*self.group_by, self.season_column),
            observe=lambda row: {"won": row.get("won")},
        ):
            games = len(past)
            wins = sum(1 for _, observation in past if observation.get("won"))  # type: ignore[union-attr]
            cells[index] = {
                "season_games_prior": games,
                "season_wins_prior": wins,
                "season_win_pct_prior": (wins / games) if games else None,
                window_end_column: past[-1][0] if past else None,
            }
        return finalise(cells, self.name)


@dataclass(frozen=True, slots=True)
class OpponentFormStep(WindowedStep):
    """Mirror the opponent's ALREADY-COMPUTED form onto each row.

    The single largest gap in the original feature set: the frame carried
    `opponent_team_id` and nothing derived from it, so every model built
    on it was predicting a game while looking at one team. Rest, pace and
    form all describe the wrong half of the matchup on their own.

    Cheap because the team-game frame already holds two rows per game.
    The opponent's prior form is literally the sibling row's value, so
    this is a lookup rather than a second pass over history -- and it
    inherits that row's window end, which is the tip-off of the most
    recent game feeding the OPPONENT's average. That timestamp is already
    strictly before the shared game, so the guard's window check passes
    for the same reason the underlying rolling step's did.

    Runs AFTER the rolling step whose columns it mirrors; `value_columns`
    naming a column that does not exist yet is a contract error, not a
    silent null.
    """

    value_columns: tuple[str, ...]
    source_window_end_column: str
    opponent_key: str = "opponent_team_id"
    team_key: str = "team_id"
    game_key: str = "game_id"
    label: str = "opponent_form"

    def __post_init__(self) -> None:
        if not self.value_columns:
            raise StepContractError("opponent form step needs at least one value column")

    @classmethod
    def mirroring(cls, source: WindowedStep, *, label: str | None = None):
        """Build a mirror from the step whose columns it copies.

        Deriving the names instead of retyping them removes the obvious
        failure mode -- a rolling step reconfigured to window=3 while its
        mirror still asks for `_mean_5`. It does NOT make the pair
        immune to `Pipeline.replace_step`, which swaps by name and leaves
        this mirror pointing at the old columns; that still fails, but it
        fails loudly at the frame contract rather than emitting nulls.
        Mirrors and their sources are a pair, and thinning one means
        thinning both.
        """
        window_end = source.provenance.window_end_column
        if window_end is None:
            raise StepContractError(
                f"cannot mirror {source.name!r}: it publishes no window-end column"
            )
        return cls(
            value_columns=source.output_columns,
            source_window_end_column=window_end,
            label=label or f"opponent_{source.name}",
        )

    @property
    def name(self) -> str:
        return self.label

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"opponent_{column}" for column in self.value_columns)

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(*self.output_columns, f"{self.label}{WINDOW_END_SUFFIX}"),
            window_end_column=f"{self.label}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        self._require_columns(
            frame,
            (
                self.game_key,
                self.team_key,
                self.opponent_key,
                self.source_window_end_column,
                *self.value_columns,
            ),
        )
        window_end_column = f"{self.label}{WINDOW_END_SUFFIX}"
        by_game_team = {
            (row[self.game_key], row[self.team_key]): row for row in frame.rows
        }

        cells: list[Row] = []
        for row in frame.rows:
            sibling = by_game_team.get((row[self.game_key], row[self.opponent_key]))
            if sibling is None:
                # The opponent's row was filtered out (a non-franchise
                # exhibition side, say). Null rather than an invented
                # value, and no window end to publish.
                cells.append(
                    {**{c: None for c in self.output_columns}, window_end_column: None}
                )
                continue
            cell: dict[str, object] = {
                f"opponent_{column}": sibling.get(column) for column in self.value_columns
            }
            cell[window_end_column] = sibling.get(self.source_window_end_column)
            cells.append(cell)
        return tuple(cells)
