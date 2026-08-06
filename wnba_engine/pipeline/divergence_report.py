"""Read the divergence log as a paper-trade ledger.

Profit is computed at the price actually recorded, via the same
`american_to_profit` the rest of this repo grades with -- never a flat
-110, which MODELING_FINDINGS.md records as the assumption that made
several dead strategies look alive.
"""

from __future__ import annotations

from wnba_engine.analysis.clv import american_to_profit
from wnba_engine.analysis.divergence_report import (
    GradedBet,
    LedgerStats,
    split_by_regime,
    summarise,
)
from wnba_engine.db.pool import Database

_SELECT = """
SELECT edge, in_play, price_survived, clv, won, book_odds
FROM divergence_observations
ORDER BY observed_at
"""


def load_ledger(db: Database) -> tuple[GradedBet, ...]:
    with db.connection() as conn:
        rows = conn.execute(_SELECT).fetchall()
    return tuple(
        GradedBet(
            edge=float(edge),
            in_play=bool(in_play),
            survived=survived,
            clv=float(clv) if clv is not None else None,
            won=won,
            profit=(
                None
                if won is None
                else (american_to_profit(int(book_odds)) if won else -1.0)
            ),
        )
        for edge, in_play, survived, clv, won, book_odds in rows
    )


def _fmt(stats: LedgerStats, label: str) -> str:
    if stats.n == 0:
        return f"  {label:<9} no observations yet"
    survival = (
        f"{100 * stats.survival_rate:5.1f}% ({stats.n_survived}/{stats.n_survival_graded})"
        if stats.survival_rate is not None
        else "  not yet rechecked"
    )
    clv = (
        f"{100 * stats.mean_clv:+6.2f} pts"
        + (f"  t={stats.clv_t:+5.2f}" if stats.clv_t is not None else "  t=n/a")
        + f"  n={stats.n_clv}"
        if stats.mean_clv is not None
        else "  not yet graded"
    )
    roi = (
        f"{100 * stats.roi:+7.2f}%"
        + (f"  t={stats.roi_t:+5.2f}" if stats.roi_t is not None else "  t=n/a")
        + f"  n={stats.n_settled}"
        if stats.roi is not None
        else "  nothing settled"
    )
    return (
        f"  {label:<9} n={stats.n:<5} mean edge {100 * stats.mean_edge:5.2f}%\n"
        f"      survival  {survival}\n"
        f"      CLV       {clv}\n"
        f"      ROI       {roi}   <- noise until n is in the thousands"
    )


def format_report(bets: tuple[GradedBet, ...]) -> str:
    pre, live = split_by_regime(bets)
    overall = summarise(bets)
    lines = [
        "divergence paper-trade ledger",
        "",
        _fmt(pre, "PRE-TIP"),
        "",
        _fmt(live, "IN-PLAY"),
        "",
    ]
    if overall.n == 0:
        lines.append("  Nothing logged yet. The agent records only when a book price")
        lines.append("  sits below the venue's fair value on >= $1,000 of volume.")
    elif not pre.ready_for_review and not live.ready_for_review:
        need = max(0, 120 - max(pre.n_clv, live.n_clv))
        lines.append(f"  Not ready to judge: ~{need} more graded observations for t=3 on CLV.")
        lines.append("  Do not read ROI yet -- it needs roughly 10,600 bets, not 120.")
    else:
        lines.append("  Enough graded observations to read CLV. Survival first:")
        lines.append("  an edge that does not survive to the next check was never takeable.")
    return "\n".join(lines)


def build_divergence_report(db: Database) -> str:
    return format_report(load_ledger(db))
