"""Paper-trade ledger for the divergence log.

Turns recorded observations into the two numbers that decide whether the
strategy is real, and deliberately does NOT lead with profit.

**Judge this on CLV and survival, not ROI.** A 0.97 point CLV implies a
true edge near 1.94% ROI; against a per-bet SD of ~1.0 that needs about
10,645 bets to reach t=2, while CLV reaches t=3 in roughly 117. Reading
ROI early is how a real edge gets abandoned and a fake one gets funded --
simulating a genuine +1.94% edge at n=915 still shows a LOSS 28% of the
time. ROI is reported here because people will look for it, with its own
t-stat next to it so it can be read as the noise it will be for months.

`survival_rate` is the in-play discriminator. A large in-play edge that
never survives to the next check is a price that did not exist.
"""

from __future__ import annotations

import math
import statistics as st
from collections.abc import Sequence
from dataclasses import dataclass

#: Observations needed before CLV is worth reading, from the power
#: calculation above. Not a hard gate -- the report prints regardless --
#: but below this a CLV number is not evidence of anything.
CLV_REVIEW_THRESHOLD = 120


@dataclass(frozen=True, slots=True)
class GradedBet:
    """One observation, as much of it as has been graded."""

    edge: float
    in_play: bool
    survived: bool | None = None
    clv: float | None = None
    won: bool | None = None
    profit: float | None = None


@dataclass(frozen=True, slots=True)
class LedgerStats:
    n: int = 0
    n_survived: int = 0
    n_survival_graded: int = 0
    survival_rate: float | None = None
    mean_edge: float = 0.0
    n_clv: int = 0
    mean_clv: float | None = None
    clv_t: float | None = None
    n_settled: int = 0
    roi: float | None = None
    roi_t: float | None = None
    ready_for_review: bool = False


def _t_stat(values: Sequence[float]) -> float | None:
    if len(values) < 3:
        return None
    sd = st.stdev(values)
    if sd == 0:
        return None
    return st.mean(values) / (sd / math.sqrt(len(values)))


def summarise(bets: Sequence[GradedBet]) -> LedgerStats:
    """Aggregate a set of graded observations.

    Each metric counts only the rows that HAVE that grade. A row logged
    ten seconds ago has no closing price and must not dilute the CLV mean
    toward zero -- which is what happens if ungraded rows are read as 0.0,
    and it would make the strategy look weaker the more actively it ran.
    """
    if not bets:
        return LedgerStats()

    survival = [b.survived for b in bets if b.survived is not None]
    clvs = [b.clv for b in bets if b.clv is not None]
    profits = [b.profit for b in bets if b.profit is not None]

    return LedgerStats(
        n=len(bets),
        n_survived=sum(1 for s in survival if s),
        n_survival_graded=len(survival),
        survival_rate=(sum(1 for s in survival if s) / len(survival)) if survival else None,
        mean_edge=st.mean([b.edge for b in bets]),
        n_clv=len(clvs),
        mean_clv=st.mean(clvs) if clvs else None,
        clv_t=_t_stat(clvs),
        n_settled=len(profits),
        roi=st.mean(profits) if profits else None,
        roi_t=_t_stat(profits),
        ready_for_review=len(clvs) >= CLV_REVIEW_THRESHOLD,
    )


def split_by_regime(
    bets: Sequence[GradedBet],
) -> tuple[LedgerStats, LedgerStats]:
    """(pre-tip, in-play). Always report these apart.

    Pooling them hides the entire question. In-play shows divergence four
    times as often and five times as large, and that is exactly what stale
    quotes look like, so a pooled mean is a blend of a measured effect and
    an unmeasured one.
    """
    return (
        summarise([b for b in bets if not b.in_play]),
        summarise([b for b in bets if b.in_play]),
    )
