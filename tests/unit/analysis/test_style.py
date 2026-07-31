"""Unit tests for style space.

The arithmetic is small. What matters is the JUDGEMENT: that scaling
happens before distance (or the space is just whichever dimension has the
biggest units), and that self-matches are included for comparables but
excluded for uniqueness.
"""

from __future__ import annotations

import pytest

from wnba_engine.analysis.style import (
    StylePoint,
    distance,
    nearest,
    uniqueness,
    z_score,
)


def pt(label, eid, season, *coords):
    return StylePoint(label=label, entity_id=eid, season=season, coordinates=tuple(coords))


def test_scaling_stops_one_big_unit_dominating():
    """Raw pace (~80) against true-shooting (~0.55): unscaled, distance is
    entirely pace and the second dimension may as well not exist."""
    raw = [pt("a", 1, 2025, 80.0, 0.50), pt("b", 2, 2025, 81.0, 0.60),
           pt("c", 3, 2025, 82.0, 0.55)]
    scaled = z_score(raw)

    spread = [max(p.coordinates[i] for p in scaled) - min(p.coordinates[i] for p in scaled)
              for i in range(2)]
    assert spread[0] == pytest.approx(spread[1], rel=0.5)  # comparable magnitudes


def test_a_constant_dimension_contributes_nothing_rather_than_dividing_by_zero():
    scaled = z_score([pt("a", 1, 2025, 1.0, 5.0), pt("b", 2, 2025, 2.0, 5.0)])

    assert all(p.coordinates[1] == 0.0 for p in scaled)


def test_nearest_excludes_the_subject_itself():
    pts = [pt("a", 1, 2025, 0.0, 0.0), pt("b", 2, 2025, 1.0, 0.0)]

    result = nearest(pts, pts[0], limit=5)

    assert [n.point.label for n in result] == ["b"]


def test_nearest_keeps_the_subjects_own_other_seasons_by_default():
    """A player's prior season being her closest comparable is the best
    evidence the space is meaningful -- it must not be filtered away."""
    pts = [pt("x 2025", 1, 2025, 0.0, 0.0), pt("x 2024", 1, 2024, 0.1, 0.0),
           pt("y 2025", 2, 2025, 3.0, 0.0)]

    result = nearest(pts, pts[0], limit=1)

    assert result[0].point.label == "x 2024"


def test_uniqueness_ignores_the_subjects_own_seasons():
    """Otherwise a player nobody resembles scores as highly typical,
    because she resembles herself."""
    pts = [pt("x 2025", 1, 2025, 0.0, 0.0), pt("x 2024", 1, 2024, 0.05, 0.0),
           pt("y 2025", 2, 2025, 4.0, 0.0), pt("z 2025", 3, 2025, 4.1, 0.0)]

    ranked = dict((p.label, d) for p, d in uniqueness(pts))

    # x is far from everyone who isn't x, despite a near-identical self-match
    assert ranked["x 2025"] > ranked["y 2025"]
    assert ranked["x 2025"] == pytest.approx(4.0)


def test_uniqueness_is_ranked_most_unusual_first():
    pts = [pt("a", 1, 2025, 0.0, 0.0), pt("b", 2, 2025, 0.1, 0.0), pt("far", 3, 2025, 9.0, 0.0)]

    assert uniqueness(pts)[0][0].label == "far"


def test_distance_is_symmetric_and_zero_on_itself():
    a, b = pt("a", 1, 2025, 1.0, 2.0), pt("b", 2, 2025, 4.0, 6.0)

    assert distance(a, b) == pytest.approx(5.0)
    assert distance(a, b) == pytest.approx(distance(b, a))
    assert distance(a, a) == 0.0


def test_scaling_an_empty_population_is_not_an_error():
    assert z_score([]) == ()
