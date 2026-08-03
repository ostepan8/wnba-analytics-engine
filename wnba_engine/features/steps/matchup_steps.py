"""Features of the MATCHUP rather than of either team.

FEATURE_ROADMAP.md ss3 records that the frame carried `opponent_team_id`
and derived nothing from it until `OpponentFormStep.mirroring()` landed.
Mirroring closed half the gap -- each row can now see the opponent's form
-- but a mirror only puts two numbers side by side. The features here are
the ones that exist only in the RELATIONSHIP between them:

- `RestAdvantageStep` -- rest matters relatively. Two days off is an
  advantage against a back-to-back and a disadvantage against four.
- `PaceInteractionStep` -- two fast teams do not play a fast game
  because either is fast; they play one because BOTH are.
- `HeadToHeadStep` -- what has actually happened when these two have
  met, which no amount of describing either team separately produces.

The two row-local steps here read columns an earlier mirror produced, so
they are cheap and cannot leak by construction. `HeadToHeadStep` is
windowed and pays the usual tax: it publishes the tip-off of the most
recent prior meeting, and the guard asserts that instant is strictly
before this game.

The mirrors themselves are `derivation.OpponentFormStep`; nothing here
re-implements them. As that class's docstring says, a mirror and its
source are a PAIR -- removing `rest_days` from a strategy without also
removing the rest mirror and this step fails at the frame contract rather
than quietly emitting nulls.
"""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import RowMapStep, WindowedStep
from wnba_engine.features.steps._windowing import (
    WINDOW_END_SUFFIX,
    finalise,
    mean_of,
    numeric,
    trailing_walk,
)


@dataclass(frozen=True, slots=True)
class RestAdvantageStep(RowMapStep):
    """Rest RELATIVE to the opponent, plus the back-to-back edge.

    FEATURE_ROADMAP.md files this under ss1 and its suggested-order entry
    files it under ss3, and ss3 is the honest home: it needs the opponent
    mirror, and the absolute `rest_days` it is derived from has been in
    the frame since the first build.

    Two columns because they answer different questions and the second is
    not recoverable from the first. `rest_advantage` is continuous and
    says how much more rest this team had. `back_to_back_edge` is the
    discrete case that dominates the schedule literature: playing a
    rested team on the second night of a back-to-back is not "one day
    less rest", it is a categorically different game, and a linear term
    in a difference of days cannot express a kink.

    Nulls propagate rather than being filled with zero. A team's first
    game of the season has no `rest_days`, and calling that "equal rest"
    would invent the one value most likely to look like the average.

    KNOWN DISTORTION, INHERITED AND AMPLIFIED. `RestDaysStep` groups by
    team only, not by (team, season), so a team's first game of a season
    reports the elapsed time since its LAST game of the previous one --
    truthfully, and uselessly. Measured against this database at
    as_of=2026-07-29: `rest_days` exceeds 30 days on 58 of 2,541 rows
    (2.3%), reaching 279. That was already true of `rest_days` and of
    everything built on it; the difference here is that two teams opening
    their seasons on different dates produce a `rest_advantage` of up to
    +/-240 days, which is 34 rows (1.3%) above +/-10 and 10 rows above
    +/-30.

    Deliberately NOT clamped. A clamp would replace a true-but-useless
    number with an invented one, and the boundary rows are identifiable
    without it: `season_games_prior == 0` is exactly the affected set, and
    `filtering.MinimumPriorGamesStep` is the sanctioned way to drop them
    -- the same answer this package already gives for a rolling average
    with no history behind it.
    """

    rest_column: str = "rest_days"
    opponent_rest_column: str = "opponent_rest_days"
    back_to_back_column: str = "is_back_to_back"
    opponent_back_to_back_column: str = "opponent_is_back_to_back"
    step_name: str = "rest_advantage"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return ("rest_advantage", "back_to_back_edge")

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        own, opponent = row.get(self.rest_column), row.get(self.opponent_rest_column)
        advantage = (
            None if own is None or opponent is None else float(own) - float(opponent)  # type: ignore[arg-type]
        )
        own_b2b = row.get(self.back_to_back_column)
        opponent_b2b = row.get(self.opponent_back_to_back_column)
        if own_b2b is None or opponent_b2b is None:
            edge: int | None = None
        else:
            # +1: only the OPPONENT is on the second night. -1: only we
            # are. 0 covers both "neither" and "both", which are the same
            # situation from a relative-advantage point of view even
            # though they are very different games -- `is_back_to_back`
            # and `opponent_is_back_to_back` remain in the frame to
            # separate them.
            edge = int(bool(opponent_b2b)) - int(bool(own_b2b))
        return {"rest_advantage": advantage, "back_to_back_edge": edge}


@dataclass(frozen=True, slots=True)
class PaceInteractionStep(RowMapStep):
    """How fast the GAME is likely to be, from both teams' rolling pace.

    Pace is the clearest case in the frame where an interaction is the
    real quantity: possessions are shared, so a game's tempo is a
    negotiation between two teams and neither team's own number predicts
    it alone.

    FEATURE_ROADMAP.md phrases the target as "both fast / both slow",
    which invites two boolean flags and a threshold. There is deliberately
    no threshold here, for two reasons:

    - Any threshold fitted on the frame is cross-sectional -- the row
      being classified contributes to the cut point. That is the
      documented limitation of every FittedStep in this package, and it
      is avoidable here rather than merely tolerable.
    - Any threshold hard-coded is an era claim. League pace drifts, and a
      number that meant "fast" in 2022 is a different percentile in 2026.

    The three summary columns carry the same information continuously and
    without either problem. Both-fast is exactly a high `pace_pair_min`;
    both-slow is exactly a low `pace_pair_max`; a mismatch is a large
    `pace_pair_gap`. A model that wants the buckets can find them, and one
    that wants the gradient is not forced through a step function.

    `pace_pair_mean` deliberately is NOT the predicted game pace -- the
    slower team tends to dictate more than the average implies, which is
    exactly the asymmetry `pace_pair_min` is there to expose.
    """

    pace_column: str = "pace_mean_5"
    opponent_pace_column: str = "opponent_pace_mean_5"
    step_name: str = "pace_interaction"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return ("pace_pair_mean", "pace_pair_min", "pace_pair_max", "pace_pair_gap")

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        own, opponent = row.get(self.pace_column), row.get(self.opponent_pace_column)
        if own is None or opponent is None:
            # `pace` is null wherever balldontlie has no advanced-stats
            # row, and a rolling pace over zero such games is null too.
            # Halving a single team's pace to stand in for the pair would
            # be a number nobody measured.
            return dict.fromkeys(self.output_columns)
        a, b = float(own), float(opponent)  # type: ignore[arg-type]
        return {
            "pace_pair_mean": (a + b) / 2.0,
            "pace_pair_min": min(a, b),
            "pace_pair_max": max(a, b),
            "pace_pair_gap": abs(a - b),
        }


@dataclass(frozen=True, slots=True)
class HeadToHeadStep(WindowedStep):
    """Prior meetings between these two teams, EXCLUDING this one.

    The exclusion is the hazard FEATURE_ROADMAP.md names for both ss3
    head-to-head rows, and it is handled the same structural way every
    other window here is: `trailing_walk` appends a meeting to the pair's
    history only after the row for that meeting has been summarised, so
    the current game cannot be one of its own prior meetings.

    Keyed on the ORDERED pair `(team_id, opponent_team_id)`, not on an
    unordered one. A team-game frame already holds both directions of
    every game as separate rows, so team A's row accumulates A's results
    against B and team B's row accumulates B's against A -- which is what
    "our record against them" means. Keying on a sorted pair would make
    `h2h_win_pct_prior` ambiguous about whose win rate it is.

    `season_column` set means "this season only" -- typically 3-4 prior
    meetings, so `h2h_games_prior` is usually 0-3 and the win percentage
    is a very noisy statistic. Set to None it spans every season in
    scope, which trades sample size for relevance across roster turnover.
    Both are offered because FEATURE_ROADMAP.md asks for both, and
    neither is obviously the better one.

    A caveat the roadmap makes for archetype matchups applies here too and
    is not solved by this step: head-to-head record is CONFOUNDED WITH
    QUALITY. A team that is 6-0 against another is usually just better,
    not matchup-proof. `h2h_margin_mean_prior` next to the same team's
    overall rolling margin is the comparison that separates the two, so
    both are kept rather than only the record.
    """

    prefix: str
    team_key: str = "team_id"
    opponent_key: str = "opponent_team_id"
    season_column: str | None = "season"
    outcome_column: str = "won"
    margin_column: str = "point_margin"
    #: How many prior meetings to use. None means all of them within the
    #: key. A cap is offered because a multi-season head-to-head reaches
    #: back through roster turnover, and "the last 6 meetings" is a
    #: different and defensible question from "every meeting since 2022".
    window: int | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if not self.prefix:
            raise StepContractError("head-to-head step needs a column prefix")
        if self.window is not None and self.window < 1:
            raise StepContractError(
                f"head-to-head window must be >= 1 meetings, got {self.window}"
            )

    @property
    def name(self) -> str:
        return self.label or f"head_to_head_{self.prefix}"

    @property
    def output_columns(self) -> tuple[str, ...]:
        return (
            f"{self.prefix}_games_prior",
            f"{self.prefix}_wins_prior",
            f"{self.prefix}_win_pct_prior",
            f"{self.prefix}_margin_mean_prior",
        )

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.WINDOWED,
            adds_columns=(*self.output_columns, f"{self.name}{WINDOW_END_SUFFIX}"),
            window_end_column=f"{self.name}{WINDOW_END_SUFFIX}",
        )

    def compute(self, frame: FeatureFrame, context: FeatureContext) -> tuple[Row, ...]:
        del context
        needed = (self.team_key, self.opponent_key, self.outcome_column, self.margin_column)
        self._require_columns(
            frame, needed if self.season_column is None else (*needed, self.season_column)
        )
        key_columns = (
            (self.team_key, self.opponent_key)
            if self.season_column is None
            else (self.team_key, self.opponent_key, self.season_column)
        )
        games, wins, win_pct, margin_mean = self.output_columns
        window_end = f"{self.name}{WINDOW_END_SUFFIX}"
        cells: list[Row | None] = [None] * len(frame.rows)

        for index, _row, past in trailing_walk(
            frame,
            self.name,
            group_by=key_columns,
            observe=lambda row: {
                self.outcome_column: row.get(self.outcome_column),
                self.margin_column: row.get(self.margin_column),
            },
        ):
            meetings = past if self.window is None else past[-self.window :]
            outcomes = numeric(meetings, self.outcome_column)
            cells[index] = {
                games: len(meetings),
                # Counted over meetings with a KNOWN result, so a
                # scoreless game does not silently become a loss.
                wins: int(sum(outcomes)),
                win_pct: (sum(outcomes) / len(outcomes)) if outcomes else None,
                margin_mean: mean_of(numeric(meetings, self.margin_column)),
                window_end: meetings[-1][0] if meetings else None,
            }
        return finalise(cells, self.name)


__all__ = [
    "HeadToHeadStep",
    "PaceInteractionStep",
    "RestAdvantageStep",
]
