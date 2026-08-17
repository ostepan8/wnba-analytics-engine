"""What a team is actually missing, in minutes and production.

An injury report names people. It does not say what they were doing, and that
is the part that moves a total: "three out" is the same headline whether it is
three end-of-bench players or a 34-minute leading scorer plus two starters. The
number that matters is the production removed from the floor.

The overlooked half is the questionable player. She is not on anybody's "out"
list, so a reader skims past her -- but a game-time decision on a 30-minute
starter is a far larger swing than a ruled-out reserve, precisely because it is
unresolved when the number is set.

So absences are bucketed by what the designation actually claims:

    out       Out, and Doubtful ("unlikely") -- treat as gone
    at_risk   Questionable, Day-To-Day -- a real chance of not playing
    likely    Probable, Available -- listed, expected to play

Descriptive throughout. Summing what a missing player averaged is not a
forecast of what her team will now score; it is a statement about what has been
removed, and the reader does the rest.
"""

from __future__ import annotations

from typing import Any

# Ruled out, or good as. "Doubtful" is the league's word for unlikely, so it
# sits with Out rather than in the middle where it would read as a coin flip.
OUT_STATUSES = frozenset({"out", "doubtful"})

# Genuinely undecided. This is the bucket a scoreboard normally throws away.
AT_RISK_STATUSES = frozenset({"questionable", "day-to-day"})

# Listed but expected to play. Kept visible: "was listed, expected to play" is
# different information from not being on the report at all.
LIKELY_STATUSES = frozenset({"probable", "available"})

BUCKETS = ("out", "at_risk", "likely")

_TOTALLED = ("minutes", "points", "rebounds", "assists")


def bucket(status: str | None) -> str | None:
    """Which availability bucket a designation falls in, or None if unknown.

    An unrecognised status returns None rather than defaulting into `out`. A
    status we do not understand is not evidence that somebody is unavailable,
    and quietly counting it as one would overstate every total below it.
    """
    value = (status or "").strip().lower()
    if value in OUT_STATUSES:
        return "out"
    if value in AT_RISK_STATUSES:
        return "at_risk"
    if value in LIKELY_STATUSES:
        return "likely"
    return None


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def summarise_absences(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group one team's listed players by bucket, with the production in each.

    Each row is expected to carry a `status` and this season's per-game
    averages. A player with no games played contributes nothing to the totals
    but is still listed -- a signing who has not debuted is on the report and
    is not missing production.
    """
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in BUCKETS}
    for row in rows:
        name = bucket(row.get("status"))
        if name is not None:
            grouped[name].append(row)

    summary: dict[str, Any] = {}
    for name, members in grouped.items():
        members.sort(key=lambda row: _number(row.get("minutes")), reverse=True)
        summary[name] = {
            "players": members,
            "count": len(members),
            **{
                field: round(sum(_number(row.get(field)) for row in members), 1)
                for field in _TOTALLED
            },
        }
    return summary


def share_of(value: float | None, team_total: Any) -> float | None:
    """`value` as a fraction of a team per-game total, or None when unusable.

    None rather than zero when the denominator is missing or zero: "0% of the
    scoring is missing" is a claim, and we would not have earned it.
    """
    total = _number(team_total)
    if value is None or total <= 0:
        return None
    return round(float(value) / total, 3)
