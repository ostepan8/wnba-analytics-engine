"""Play-by-play derived features (FEATURE_ROADMAP.md ss9).

509,119 plays across 1,300 games had produced exactly zero features before
this module. The aggregation from plays to one row per (game, team) lives
in `feature_repo` alongside the box score, because it answers the same kind
of question -- what happened in this game -- and reconciles against the
final score on 99.8% of team-games.

**Everything the loader adds is a TARGET.** Quarter scoring, largest run,
lead changes and clutch points all describe the game being predicted. They
are in `derivation.TARGET_COLUMNS` for the same reason `points_scored` is,
and the features are the rolled versions built here from PAST rows. That
distinction has now been got wrong twice in this package -- once for the
advanced stats, once for these -- so it is worth stating plainly rather
than assuming.

The two steps here are the ones a plain rolling mean cannot express:

| step | question |
|---|---|
| `ScoringProfileStep` | WHEN in a game does this team score |
| `GameVolatilityStep` | how chaotic are its games, independent of who wins |

Both are ROW_LOCAL and read only columns already in the frame, so they can
be rolled by the ordinary windowed steps afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.frame import Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import RowMapStep

#: The four regulation periods, in order.
PERIOD_COLUMNS: tuple[str, ...] = (
    "period_1_points",
    "period_2_points",
    "period_3_points",
    "period_4_points",
)


@dataclass(frozen=True, slots=True)
class ScoringProfileStep(RowMapStep):
    """WHERE in a game a team's points came from, as shares.

    Shares rather than raw quarter points, because the raw version is
    already available and correlates almost perfectly with total scoring --
    a team that scores 90 outscores a team that scores 70 in every quarter.
    Normalising asks the different question: is this team front-loaded or
    a closer, *given* how much it scored.

    `second_half_share` is not redundant with the quarter shares even
    though it is their sum. Halves are how rotations and adjustments
    actually work, and a model reading one number rather than two spends
    fewer degrees of freedom on the same claim.

    Null regulation total gives nulls throughout -- 77 of 1,377 games have
    no play-by-play at all, and a zero share would assert those teams
    scored nothing in every quarter.
    """

    step_name: str = "scoring_profile"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return (
            "period_1_share",
            "period_2_share",
            "period_3_share",
            "period_4_share",
            "second_half_share",
            "clutch_share",
        )

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        quarters = [_as_float(row.get(column)) for column in PERIOD_COLUMNS]
        if any(value is None for value in quarters):
            return dict.fromkeys(self.output_columns)
        total = sum(q for q in quarters if q is not None)
        if total <= 0:
            return dict.fromkeys(self.output_columns)
        clutch = _as_float(row.get("clutch_points"))
        shares = {
            f"period_{index + 1}_share": (value or 0.0) / total
            for index, value in enumerate(quarters)
        }
        shares["second_half_share"] = ((quarters[2] or 0.0) + (quarters[3] or 0.0)) / total
        # Clutch points are a subset of period 4 and overtime, so this is a
        # share of REGULATION scoring and can exceed period_4_share only in
        # an overtime game -- which is informative rather than a bug.
        shares["clutch_share"] = None if clutch is None else clutch / total
        return shares


@dataclass(frozen=True, slots=True)
class GameVolatilityStep(RowMapStep):
    """How chaotic this team's game was, independent of who won.

    `lead_changes` and `largest_lead` are properties of the game, so both
    of its rows carry identical values -- which means a model reading them
    across a full frame sees each game twice. That is exactly the
    double-counting that inflated a `pace_gap` t-statistic from -2.61 to
    -3.66 elsewhere in this project, so it is called out here rather than
    left to be rediscovered.

    `run_dominance` is the one column that IS team-specific: a team's own
    largest run relative to the largest lead the game ever saw. High means
    its scoring arrived in bursts that translated into separation; low
    means it scored steadily, or that its runs were answered.
    """

    step_name: str = "game_volatility"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return ("run_dominance", "went_to_overtime", "lead_change_rate")

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        run = _as_float(row.get("largest_run"))
        lead = _as_float(row.get("largest_lead"))
        changes = _as_float(row.get("lead_changes"))
        overtime = _as_float(row.get("overtime_points"))
        total = sum(
            value for value in (_as_float(row.get(c)) for c in PERIOD_COLUMNS) if value
        )
        return {
            "run_dominance": None if run is None or not lead else run / lead,
            # None, not False, when there is no play-by-play: "we do not
            # know" and "regulation" are different claims and a rolling
            # overtime RATE must skip the first rather than count it.
            "went_to_overtime": None if overtime is None and total == 0 else bool(overtime),
            # Per 100 points of this team's regulation scoring, so a
            # high-pace game does not look chaotic merely for being long.
            "lead_change_rate": (
                None if changes is None or total <= 0 else 100.0 * changes / total
            ),
        }


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]


__all__ = [
    "PERIOD_COLUMNS",
    "GameVolatilityStep",
    "ScoringProfileStep",
]
