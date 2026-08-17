"""Ranking a whole day's props into the handful worth looking at first.

A scoreboard with five games carries a few hundred priced props. Rendering all
of them is the same as rendering none: the reader has no way in. This picks the
ones where the live price and the recent frequency disagree most, which is the
only ordering that is about the data rather than about alphabetical accident.

The gap is NOT an edge. It is the difference between two descriptions of the
same player -- what a prediction market currently charges for the over, and how
often she has actually gone past that number lately. Those can differ for
reasons the frequency cannot see: an injury, a rotation change, a blowout run,
or simply ten games being ten games. MODELING_FINDINGS.md records that no
forecasting edge has been produced from this data, and this module does not
produce one either. It sorts.

Read-only throughout; no order placement anywhere in this codebase
(ROADMAP.md non-goals).
"""

from __future__ import annotations

from typing import Any

# A slate headline is a stronger claim than a row in a table, so it needs a
# bigger sample than the four decided games that let a rate be printed at all.
MIN_DECIDED_FOR_SLATE = 6

# How many make the cut. Enough to scan, few enough to actually read.
TOP_SLATE_TRENDS = 12

# Prices this extreme are excluded, and this is the single most important line
# in the module.
#
# Ranking by the size of a disagreement puts the tails on top, and the tails are
# where the disagreements are fake. A market at 0.05% on "over 2.5 rebounds" is
# not disputing a 40% hit rate; it is a settled contract, a dead book, or -- the
# case that dominated a real slate -- a player who has been ruled out, which the
# venue knows and a frequency of her last ten games cannot. Six of the first
# twelve rows were scratched players before this existed.
PRICE_BAND = (0.03, 0.97)


def window(windows: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    """One named window out of the list `trends_for_line` produced."""
    for entry in windows:
        if entry.get("label") == label:
            return entry
    return None


def current_streak(recent: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The run of consecutive overs or unders ending at the most recent game.

    A push breaks nothing and continues nothing -- it is not a result -- so it
    is skipped rather than treated as the opposite outcome.
    """
    decided = [row for row in recent if row.get("cleared") in {"over", "under"}]
    if not decided:
        return None

    direction = decided[0]["cleared"]
    length = 0
    for row in decided:
        if row["cleared"] != direction:
            break
        length += 1
    return {"direction": direction, "length": length}


def price_gap(prop: dict[str, Any]) -> float | None:
    """Recent hit rate minus what the market charges for the over.

    None when either side is missing or the window is too thin to state as a
    percentage -- a gap computed against a rate we refused to print would be
    that same rate wearing a different name.
    """
    row = _rank_row(prop, min_decided=MIN_DECIDED_FOR_SLATE)
    return None if row is None else float(row["gap"])


def _rank_row(prop: dict[str, Any], *, min_decided: int) -> dict[str, Any] | None:
    """One ranked row, or None when this prop cannot be ranked honestly."""
    l10 = window(prop.get("windows") or [], "L10")
    price = prop.get("over_probability")
    if l10 is None or l10.get("rate") is None or price is None:
        return None
    if not PRICE_BAND[0] <= float(price) <= PRICE_BAND[1]:
        return None
    if l10["overs"] + l10["unders"] < min_decided:
        return None
    return {
        **{
            key: prop[key]
            for key in (
                "game_id",
                "player_id",
                "full_name",
                "prop_type",
                "line",
                "over_probability",
                "provider",
            )
            if key in prop
        },
        "l10": l10,
        "season": window(prop["windows"], "Season"),
        "streak": current_streak(prop.get("recent") or []),
        "gap": round(float(l10["rate"]) - float(price), 3),
    }


def rank_slate_trends(
    props: list[dict[str, Any]],
    *,
    limit: int = TOP_SLATE_TRENDS,
    min_decided: int = MIN_DECIDED_FOR_SLATE,
    unavailable: set[int] | None = None,
) -> list[dict[str, Any]]:
    """The props whose price and recent frequency disagree most, biggest first.

    `unavailable` is the set of player ids ruled out for the day. Their props
    are dropped rather than ranked: a last-ten hit rate for someone who is not
    playing is not a claim about tonight, and because the venues price a
    scratched player's over near zero, those rows otherwise sort straight to the
    top -- the largest gaps on the board and every one of them meaningless.

    Each survivor carries the two windows it was ranked on plus its streak, so
    the ordering can be checked against what is displayed rather than taken on
    trust.
    """
    ruled_out = unavailable or set()
    ranked = [
        row
        for row in (
            _rank_row(prop, min_decided=min_decided)
            for prop in props
            if int(prop.get("player_id", -1)) not in ruled_out
        )
        if row is not None
    ]
    ranked.sort(key=lambda row: abs(float(row["gap"])), reverse=True)
    return ranked[:limit]


def gap_balance(
    props: list[dict[str, Any]],
    *,
    min_decided: int = MIN_DECIDED_FOR_SLATE,
    unavailable: set[int] | None = None,
) -> dict[str, Any]:
    """How the whole board leans, over every rankable prop rather than the top few.

    A top-twelve list where all twelve gaps point the same way looks like twelve
    findings and is usually one: threshold contracts priced conservatively, or a
    recent-form window that runs hot across the league. Counting the direction
    over the full set is what tells those apart, and it is the difference
    between a reader seeing an ordering and a reader seeing a pattern.
    """
    ruled_out = unavailable or set()
    gaps = [
        float(row["gap"])
        for row in (
            _rank_row(prop, min_decided=min_decided)
            for prop in props
            if int(prop.get("player_id", -1)) not in ruled_out
        )
        if row is not None
    ]
    if not gaps:
        return {"rankable": 0, "above": 0, "below": 0, "median_gap": None}

    gaps.sort()
    middle = len(gaps) // 2
    median = (
        gaps[middle]
        if len(gaps) % 2
        else (gaps[middle - 1] + gaps[middle]) / 2
    )
    return {
        "rankable": len(gaps),
        "above": sum(1 for gap in gaps if gap > 0),
        "below": sum(1 for gap in gaps if gap < 0),
        "median_gap": round(median, 3),
    }
