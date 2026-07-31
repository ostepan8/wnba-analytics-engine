"""Teams and players as points in a style space.

The question this answers is not "who is better" but "who plays alike".
Those are different axes, and conflating them is the usual failure of
similarity work in sport: a raw box-score vector puts every high-usage
scorer next to every other one, so the "comparables" are really just a
ranking.

Two choices keep quality out of the space:

- Player vectors use PER-36 RATES and SHARES, never totals. Minutes and
  games played describe role and health, not style.
- Team vectors deliberately exclude offensive and defensive rating. Those
  measure how WELL a team executes; pace, shot mix and the four factors
  describe WHAT it executes. A bad team and a good team that play the
  same way should be neighbours, and with ratings included they never
  are.

Every dimension is z-scored across the whole population before distances
are taken, because the raw units are incommensurable -- pace is ~80,
true-shooting is ~0.55, and unscaled Euclidean distance would be almost
entirely pace.

Pure Python on purpose: the populations here are ~600 player-seasons and
~64 team-seasons, so an O(n^2) distance sweep is microseconds and the
core package stays free of a numeric dependency (see pyproject's optional
`modeling` extra for where numpy does get used).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: Per-36 rates and shares. No totals, no minutes, no games -- see module
#: docstring on why volume must stay out of a style space.
PLAYER_DIMENSIONS: tuple[str, ...] = (
    "pts36", "reb36", "ast36", "tpm36", "stl36", "blk36", "tov36",
    "three_share", "ft_rate", "oreb_share", "usage", "ts", "astpct", "rebpct",
)

#: Four factors both ways, pace, and shot mix. NOT ortg/drtg.
TEAM_DIMENSIONS: tuple[str, ...] = (
    "pace", "efg", "tov", "oreb", "ftr", "ast",
    "d_efg", "d_tov", "d_oreb", "d_ftr",
    "paint_rate", "three_rate", "mid_rate",
)


@dataclass(frozen=True, slots=True)
class StylePoint:
    """One subject's position in style space."""

    label: str
    entity_id: int
    season: int
    coordinates: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Neighbour:
    point: StylePoint
    distance: float


def z_score(points: Sequence[StylePoint]) -> tuple[StylePoint, ...]:
    """Standardise each dimension across the population.

    Without this, distance is dominated by whichever dimension happens to
    have the largest raw units. A dimension with zero variance is left at
    0 rather than dividing by zero -- it carries no information either
    way, so it simply stops contributing.
    """
    if not points:
        return ()
    width = len(points[0].coordinates)
    means = [sum(p.coordinates[i] for p in points) / len(points) for i in range(width)]
    sds = []
    for i in range(width):
        var = sum((p.coordinates[i] - means[i]) ** 2 for p in points) / max(len(points) - 1, 1)
        sds.append(math.sqrt(var))
    return tuple(
        StylePoint(
            label=p.label,
            entity_id=p.entity_id,
            season=p.season,
            coordinates=tuple(
                (p.coordinates[i] - means[i]) / sds[i] if sds[i] > 0 else 0.0
                for i in range(width)
            ),
        )
        for p in points
    )


def distance(a: StylePoint, b: StylePoint) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a.coordinates, b.coordinates, strict=True)))


def nearest(
    points: Sequence[StylePoint],
    target: StylePoint,
    *,
    limit: int = 5,
    exclude_same_entity: bool = False,
) -> tuple[Neighbour, ...]:
    """Closest neighbours to `target`.

    `exclude_same_entity` drops the subject's OTHER seasons. Keep them for
    comparables -- a player's own prior season being the nearest point is
    the strongest available evidence that the space is meaningful -- and
    drop them for uniqueness, where "nobody plays like her except her"
    would otherwise read as "she is unremarkable".
    """
    candidates = [
        p for p in points
        if not (p.entity_id == target.entity_id and p.season == target.season)
        and not (exclude_same_entity and p.entity_id == target.entity_id)
    ]
    scored = sorted(
        (Neighbour(p, distance(target, p)) for p in candidates),
        key=lambda n: n.distance,
    )
    return tuple(scored[:limit])


def uniqueness(points: Sequence[StylePoint]) -> tuple[tuple[StylePoint, float], ...]:
    """Each subject's distance to the nearest DIFFERENT subject, descending.

    A high value means nobody else in the population plays this way. On
    the WNBA data this cleanly separates genuinely unusual profiles from
    the league's most replicated role -- see analysis/README notes.
    """
    return tuple(
        sorted(
            ((p, nearest(points, p, limit=1, exclude_same_entity=True)[0].distance)
             for p in points if len(points) > 1),
            key=lambda t: -t[1],
        )
    )
