"""Market-wide CLV report: how much is there to capture, and where?

This does NOT score a prediction -- there isn't one yet. It measures the
opportunity: how far prices drift between a market opening and closing,
which bounds what any predictor could possibly extract.

The framing matters. If prices never moved, CLV would be unattainable no
matter how good a model was, and the whole approach would be dead on
arrival. If they move but with zero mean, the market is efficient in
aggregate and the game becomes predicting WHICH ones move -- a much
narrower and more honest target than "beat the market".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wnba_engine.analysis.clv import SIDE_UNDER, ClvResult, score_pick, summarize
from wnba_engine.db.pool import Database
from wnba_engine.repositories import clv_repo

#: Movement thresholds, in probability points, for the tail breakdown.
#: A ~2pt move is roughly the width of a book's margin on a tight prop,
#: so anything beyond that is the market genuinely changing its mind
#: rather than repricing its own vig.
_TAIL_THRESHOLDS = (0.01, 0.03, 0.05)


@dataclass(frozen=True, slots=True)
class ClvMarketReport:
    pairs: int
    scored: int
    line_moved: int
    mean_clv: float | None
    sd_clv: float | None
    unmoved_price_share: float
    tail_shares: tuple[tuple[float, float], ...]

    def __str__(self) -> str:
        mean = "n/a" if self.mean_clv is None else f"{self.mean_clv:+.5f}"
        sd = "n/a" if self.sd_clv is None else f"{self.sd_clv:.5f}"
        tails = "  ".join(f">{t:.0%}: {s:.1%}" for t, s in self.tail_shares)
        return (
            f"pairs={self.pairs} scored={self.scored} line_moved={self.line_moved} "
            f"mean_clv={mean} sd={sd} never_moved={self.unmoved_price_share:.1%}  {tails}"
        )


def build_clv_report(
    db: Database,
    *,
    prop_types: Sequence[str] | None = None,
    seasons: Sequence[int] | None = None,
) -> ClvMarketReport:
    with db.connection() as conn:
        pairs = clv_repo.load_open_close_pairs(
            conn, prop_types=prop_types, seasons=seasons
        )

    # Scored from the UNDER side by convention. The choice is arbitrary
    # for a symmetric measure -- over-side CLV is the exact negative --
    # but it must be stated, or the sign of the mean is uninterpretable.
    results: tuple[ClvResult, ...] = tuple(
        score_pick(
            side=SIDE_UNDER,
            bet_line=p.open_line,
            bet_over_odds=p.open_over,
            bet_under_odds=p.open_under,
            bet_captured_at=p.open_at,
            close_line=p.close_line,
            close_over_odds=p.close_over,
            close_under_odds=p.close_under,
            close_captured_at=p.close_at,
        )
        for p in pairs
    )

    summary = summarize(results)
    moves = tuple(abs(r.clv) for r in results if r.clv is not None)
    return ClvMarketReport(
        pairs=summary.picks,
        scored=summary.scored,
        line_moved=summary.line_moved,
        mean_clv=summary.mean_clv,
        sd_clv=_stddev(tuple(r.clv for r in results if r.clv is not None)),
        unmoved_price_share=(sum(1 for m in moves if m == 0) / len(moves)) if moves else 0.0,
        tail_shares=tuple(
            (t, (sum(1 for m in moves if m > t) / len(moves)) if moves else 0.0)
            for t in _TAIL_THRESHOLDS
        ),
    )


def _stddev(values: tuple[float, ...]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
