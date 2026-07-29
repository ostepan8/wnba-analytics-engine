"""Row filters.

Ordering matters more than it looks. A filter placed AFTER a windowed
step still leaves the dropped rows inside that step's windows -- so
filtering preseason out at the end gives you a regular-season frame whose
"last 5 games" quietly includes exhibitions against Japan. Filters that
define what counts as a game therefore belong BEFORE the derivation
block; filters that define what counts as a usable ROW (minimum minutes)
belong after, because a low-minutes game is still a real game that
consumed rest.

The strategies in `wnba_engine/features/strategies.py` order them that
way, and `Pipeline.insert_after` exists so a caller adding one has to
choose a position rather than defaulting to the end.
"""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.frame import Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import FilterStep


@dataclass(frozen=True, slots=True)
class FranchiseOnlyStep(FilterStep):
    """Keep games between two real WNBA franchises.

    `teams` holds 28 rows for 15 franchises: the rest are preseason
    exhibition opponents (Brazil, Japan, Toyota Antelopes) and All-Star
    roster constructs ("TEAM CLARK", "TEAM COLLIER"), all flagged
    `is_franchise = false` by migration 0010. Both sides are checked --
    a franchise playing a national team is still not a WNBA game, and
    letting it through poisons rest-day and rolling-form windows with a
    fixture nobody models.
    """

    team_column: str = "team_is_franchise"
    opponent_column: str = "opponent_is_franchise"
    step_name: str = "franchise_only"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        return bool(row.get(self.team_column)) and bool(row.get(self.opponent_column))


@dataclass(frozen=True, slots=True)
class SeasonTypeStep(FilterStep):
    """Keep only `context.season_types`.

    Redundant with the loader's WHERE clause by design. The loader filters
    for cost (2,700 rows instead of 2,900) and this filters for
    correctness when a caller supplies rows from somewhere else -- a
    StaticRowSource, a cached frame, a hand-built fixture. Belt and
    braces is cheap here and the failure it prevents (an All-Star game in
    a rest-days window) is silent.
    """

    column: str = "season_type"
    step_name: str = "season_type"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        return row.get(self.column) in context.season_types


@dataclass(frozen=True, slots=True)
class MinimumMinutesStep(FilterStep):
    """Drop player-game rows below a minutes threshold.

    Null minutes are dropped too: `player_game_stats` stores NULL for a
    DNP (migration 0002), so a null here means the player did not appear,
    not that we failed to record how long they played.

    Placed after the derivation block in every strategy -- see this
    module's docstring. A 3-minute garbage-time appearance is noise as a
    ROW and is still a real game for the purposes of rest.
    """

    minimum: int
    column: str = "minutes"
    step_name: str = "minimum_minutes"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        minutes = row.get(self.column)
        if minutes is None:
            return False
        return float(minutes) >= self.minimum  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SeasonsStep(FilterStep):
    """Keep only `context.seasons` (empty context.seasons keeps everything)."""

    column: str = "season"
    step_name: str = "seasons"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        if not context.seasons:
            return True
        return row.get(self.column) in context.seasons


@dataclass(frozen=True, slots=True)
class MinimumPriorGamesStep(FilterStep):
    """Drop rows whose backward-looking window had too little history.

    The honest alternative to back-filling a rolling average with the
    season mean: a team's first game of 2022 has no prior form, and any
    value invented for it is a value the model will learn from. Dropping
    the row states that plainly.
    """

    minimum: int
    column: str = "season_games_prior"
    step_name: str = "minimum_prior_games"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FILTER)

    def keep(self, row: Row, context: FeatureContext) -> bool:
        prior = row.get(self.column)
        return prior is not None and int(prior) >= self.minimum  # type: ignore[arg-type]
