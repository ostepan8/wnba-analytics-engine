"""Loader steps: the only place rows enter a feature frame.

Every loader narrows the context before handing it to the source, and the
narrowing is the interesting part.

`completion_margin` exists because `games` records WHEN A GAME STARTED,
not when we learned its result. `games.home_score` is written by whichever
ESPN sync happened to run after the final buzzer, and nothing in the row
says when that was. So filtering on `start_time <= as_of` alone admits a
game that TIPPED OFF twenty minutes before the boundary and finished two
hours after it -- and its final score, which nobody could have known,
becomes an input. Subtracting a margin makes the rule "the game was over,
with room to spare, before the boundary". Four hours covers a WNBA game
(~2h15m) plus overtime and a slow sync.

The alternative -- adding a `result_known_at` column to `games` -- would
be strictly better and is a schema change this layer does not get to
make. Noted in the README as the honest fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.source import FeatureRowSource
from wnba_engine.features.step import AsOfJoinStep, SourceStep, TimeInvariantJoinStep
from wnba_engine.repositories import feature_repo

#: A WNBA game runs ~2h15m; overtime and a lagging ESPN sync add more.
#: Four hours is deliberately generous -- the cost of being wrong in this
#: direction is a handful of dropped rows near the boundary, and the cost
#: of being wrong in the other direction is a model trained on scores that
#: did not exist yet.
DEFAULT_COMPLETION_MARGIN = timedelta(hours=4)

EVENT_TIME_COLUMN = "start_time"


def _completed_by(context: FeatureContext, margin: timedelta) -> FeatureContext:
    """The context a loader actually queries with."""
    return context.with_as_of(context.as_of - margin)


@dataclass(frozen=True, slots=True)
class LoadTeamGamesStep(SourceStep):
    """Team-game grain: two rows per game, one per side."""

    source: FeatureRowSource
    completion_margin: timedelta = DEFAULT_COMPLETION_MARGIN
    step_name: str = "load_team_games"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.SOURCE,
            adds_columns=feature_repo.TEAM_GAME_COLUMNS,
            as_of_columns=(EVENT_TIME_COLUMN,),
            event_time_column=EVENT_TIME_COLUMN,
            source_tables=("games", "teams", "team_advanced_stats"),
        )

    def fetch(self, context: FeatureContext) -> tuple[Row, ...]:
        return self.source.team_games(_completed_by(context, self.completion_margin))


@dataclass(frozen=True, slots=True)
class LoadPlayerGamesStep(SourceStep):
    """Player-game grain: one row per player per game, one box-score source.

    The source filter lives in the repository (see load_player_games) --
    it has to, because a step that forgot it would produce a frame that
    passes every guard here and is still wrong by a factor of two.
    """

    source: FeatureRowSource
    completion_margin: timedelta = DEFAULT_COMPLETION_MARGIN
    step_name: str = "load_player_games"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.SOURCE,
            adds_columns=feature_repo.PLAYER_GAME_COLUMNS,
            as_of_columns=(EVENT_TIME_COLUMN,),
            event_time_column=EVENT_TIME_COLUMN,
            source_tables=("player_game_stats", "games", "players", "teams"),
        )

    def fetch(self, context: FeatureContext) -> tuple[Row, ...]:
        return self.source.player_games(_completed_by(context, self.completion_margin))


@dataclass(frozen=True, slots=True)
class JoinStandingsSnapshotStep(AsOfJoinStep):
    """Standings as they stood before each game, per (team, season).

    Reads team_standings_history, never team_standings. That distinction
    is the single loudest trap in DATA_INVENTORY.md: team_standings is a
    current-state upsert, so a naive join hands a 2023 game the 2026
    table. feature_repo refuses the name outright.

    Note this is a per-ROW as-of join, not a per-frame one -- see
    AsOfJoinStep, which documents the concrete leak the per-frame version
    produced against this exact table.

    Expect all-null columns for any game before 2026-07-09, the earliest
    captured_at that exists. Nulls here are the truthful answer; the
    `standings_captured_at` column keeps "we knew nothing" distinguishable
    from "we knew this" instead of collapsing both into a missing value.
    """

    source: FeatureRowSource
    step_name: str = "join_standings_snapshot"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.JOIN,
            adds_columns=feature_repo.STANDINGS_SNAPSHOT_COLUMNS,
            as_of_columns=("standings_captured_at",),
            source_tables=("team_standings_history",),
        )

    def observations(
        self, context: FeatureContext
    ) -> dict[tuple[object, ...], list[tuple[datetime, Row]]]:
        series: dict[tuple[object, ...], list[tuple[datetime, Row]]] = {}
        for row in self.source.standings_snapshots(context):
            captured_at = row["standings_captured_at"]
            if not isinstance(captured_at, datetime):
                raise StepContractError(
                    f"standings snapshot has a non-datetime captured_at: {captured_at!r}"
                )
            cells = {
                column: row[column] for column in feature_repo.STANDINGS_SNAPSHOT_COLUMNS
            }
            series.setdefault((row["team_id"], row["season"]), []).append(
                (captured_at, cells)
            )
        return series

    def key_for(self, row: Row) -> tuple[object, ...]:
        return (row.get("team_id"), row.get("season"))


_BIO_JUSTIFICATION = (
    "height/weight/college are 'effectively permanent' per DATA_INVENTORY.md; "
    "the mutable siblings age/jersey_number are refused by feature_repo's "
    "identifier scan, so nothing time-varying is reachable through this step."
)


@dataclass(frozen=True, slots=True)
class JoinPlayerBioStep(TimeInvariantJoinStep):
    """Permanent bio fields onto a player-grain frame.

    The only step in the subsystem allowed to add data with no as-of
    anchor, and it pays for that with a written justification that the
    StepProvenance constructor refuses to omit.
    """

    source: FeatureRowSource
    step_name: str = "join_player_bio"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.TIME_INVARIANT,
            adds_columns=feature_repo.PLAYER_BIO_COLUMNS,
            source_tables=("players",),
            justification=_BIO_JUSTIFICATION,
        )

    def lookup(self, context: FeatureContext) -> dict[tuple[object, ...], Row]:
        rows = self.source.player_bios()
        return {
            (row["player_id"],): {
                column: row[column] for column in feature_repo.PLAYER_BIO_COLUMNS
            }
            for row in rows
        }

    def key_for(self, row: Row) -> tuple[object, ...]:
        return (row.get("player_id"),)


#: Re-exported so callers composing custom strategies do not have to reach
#: into the repository module for the column tuples.
TEAM_GAME_COLUMNS = feature_repo.TEAM_GAME_COLUMNS
PLAYER_GAME_COLUMNS = feature_repo.PLAYER_GAME_COLUMNS

__all__ = [
    "DEFAULT_COMPLETION_MARGIN",
    "EVENT_TIME_COLUMN",
    "PLAYER_GAME_COLUMNS",
    "TEAM_GAME_COLUMNS",
    "JoinPlayerBioStep",
    "JoinStandingsSnapshotStep",
    "LoadPlayerGamesStep",
    "LoadTeamGamesStep",
]
