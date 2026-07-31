"""Style as a FEATURE, not a description.

wnba_engine/analysis/style.py builds season-aggregate style vectors for
comparison. Those can never enter a predictive frame -- a season
aggregate contains the games it would be used to predict. The steps here
rebuild the same idea from TRAILING WINDOWS so it is point-in-time
legitimate, then derive things a single team's vector cannot express:

- how DIFFERENT two opponents are (a stylistic mismatch is not visible in
  either team's own numbers)
- per-dimension gaps, so "fast team vs slow team" is separable from
  "good-shooting team vs bad-rebounding team"
- how fast a team's own style is CHANGING, which distinguishes a settled
  identity from a team mid-reinvention

All of these consume columns produced earlier in the pipeline. They
declare their inputs and fail loudly if a required rolling step was
removed, for the same reason OpponentFormStep does.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.step import FittedStep, RowMapStep

#: The style dimensions rolled into a trailing vector. Pace and the four
#: factors on both sides -- WHAT a team does. Ratings are deliberately
#: absent: they measure how WELL, and a mismatch feature should treat a
#: good and a bad team that play alike as similar.
STYLE_DIMENSIONS: tuple[str, ...] = (
    "pace", "efg", "tov_ratio", "oreb_pct", "ftr", "ast_pct",
    "opp_efg", "opp_tov_pct", "opp_oreb_pct", "opp_ftr",
)


@dataclass(frozen=True, slots=True)
class StyleDistanceStep(FittedStep):
    """Euclidean distance between a team's rolling style and its opponent's,
    plus the signed per-dimension gaps.

    FITTED because a distance over raw dimensions is meaningless: pace
    runs ~80 and turnover ratio ~0.14, so an unscaled norm is pace and
    nothing else. Scaling uses this frame's own spread, which is safe with
    respect to TIME (the frame has already passed the guard) but not with
    respect to the cross-section -- the row being scaled contributes to
    its own mean. That is the documented limitation of every fitted step
    here, and it matters less for a distance than for a level.

    The per-dimension gaps are the point. A single distance says "these
    teams are unalike"; `pace_gap` and `oreb_pct_gap` say HOW, and a model
    can learn that a pace mismatch matters and a free-throw-rate mismatch
    does not.
    """

    #: Explicit column names rather than a prefix convention. RollingMeanStep
    #: emits "{column}_mean_{window}" and the opponent mirror prefixes that
    #: with "opponent_", so guessing the shape here would silently look for
    #: columns nobody produces -- caught only at run time, and only because
    #: the guard compares declarations against reality.
    team_columns: tuple[str, ...]
    opponent_columns: tuple[str, ...]
    dimensions: tuple[str, ...] = STYLE_DIMENSIONS
    step_name: str = "style_distance"

    def __post_init__(self) -> None:
        if not (len(self.team_columns) == len(self.opponent_columns) == len(self.dimensions)):
            raise StepContractError(
                "style distance needs team_columns, opponent_columns and dimensions "
                f"of equal length (got {len(self.team_columns)}, "
                f"{len(self.opponent_columns)}, {len(self.dimensions)})"
            )

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return ("style_distance", *(f"{d}_gap" for d in self.dimensions))

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.FITTED, adds_columns=self.output_columns)

    def _columns(self) -> tuple[tuple[str, str], ...]:
        return tuple(zip(self.team_columns, self.opponent_columns, strict=True))

    def fit(self, frame: FeatureFrame, context: FeatureContext) -> Sequence[object]:
        del context
        required = [c for pair in self._columns() for c in pair]
        self._require_columns(frame, tuple(required))
        scales: list[float] = []
        for own, _ in self._columns():
            values = [float(r[own]) for r in frame.rows if r.get(own) is not None]
            if len(values) < 2:
                scales.append(1.0)
                continue
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            sd = math.sqrt(var)
            # A dimension with no spread cannot discriminate; scaling by 1
            # leaves its gap at ~0 rather than exploding it.
            scales.append(sd if sd > 0 else 1.0)
        return scales

    def transform_fitted(
        self, row: Row, params: Sequence[object], context: FeatureContext
    ) -> Row:
        del context
        cells: dict[str, object] = {}
        total = 0.0
        measurable = 0
        for (own, opp), scale, dim in zip(self._columns(), params, self.dimensions, strict=True):
            a, b = row.get(own), row.get(opp)
            if a is None or b is None:
                cells[f"{dim}_gap"] = None
                continue
            gap = (float(a) - float(b)) / float(scale)  # type: ignore[arg-type]
            cells[f"{dim}_gap"] = gap
            total += gap * gap
            measurable += 1
        # None, not 0.0: "we could not measure the mismatch" and "these
        # teams play identically" are opposite claims.
        cells["style_distance"] = math.sqrt(total) if measurable else None
        return cells


@dataclass(frozen=True, slots=True)
class StyleVolatilityStep(RowMapStep):
    """How far a team's recent style sits from its longer-run style.

    Distinguishes a settled identity from a team mid-reinvention -- an
    injury forcing a new rotation, a trade, a coaching change. Both look
    identical in a single rolling average, which is exactly why one window
    cannot express it.

    Row-local by construction: it compares two windows the pipeline has
    ALREADY computed, so it can see no row but its own. Both windows were
    published by windowed steps whose ends the guard has already checked.
    """

    short_columns: tuple[str, ...]
    long_columns: tuple[str, ...]
    scales: tuple[float, ...] = field(default=())
    step_name: str = "style_volatility"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=("style_volatility",))

    def __post_init__(self) -> None:
        if len(self.short_columns) != len(self.long_columns):
            raise StepContractError(
                "style volatility needs matching short and long column lists "
                f"({len(self.short_columns)} vs {len(self.long_columns)})"
            )

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        total = 0.0
        seen = 0
        for i, (short, long) in enumerate(zip(self.short_columns, self.long_columns, strict=True)):
            a, b = row.get(short), row.get(long)
            if a is None or b is None:
                continue
            scale = self.scales[i] if self.scales else 1.0
            total += ((float(a) - float(b)) / scale) ** 2
            seen += 1
        return {"style_volatility": math.sqrt(total / seen) if seen else None}
