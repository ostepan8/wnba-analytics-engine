"""Unit tests for the lead-lag statistics.

The interesting tests here are the ones that prove the method can DETECT a
lead it was given, and that it does not invent one from a series that has
none. A cross-correlation that always reports something is worse than
useless -- it would have confirmed the hypothesis regardless.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wnba_engine.analysis import lead_lag
from wnba_engine.analysis.lead_lag import PricePoint

START = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
TOL = timedelta(minutes=2, seconds=30)


def _series(values: list[float], *, step_minutes: int = 5, offset_minutes: int = 0):
    return [
        PricePoint(START + timedelta(minutes=offset_minutes + i * step_minutes), v)
        for i, v in enumerate(values)
    ]


def test_home_probability_uses_the_stated_outcome() -> None:
    """The reason this table beats the snapshot table: no inference."""
    home, away = "Atlanta Dream", "Las Vegas Aces"
    assert lead_lag.home_probability(home, 0.56, home, away) == 0.56
    assert lead_lag.home_probability(away, 0.44, home, away) == 0.56


def test_a_prop_outcome_is_not_forced_onto_a_side() -> None:
    """~19% of linked fills are props/derivatives on the same game. Forcing
    them onto the moneyline would inject unrelated prices into the series.
    """
    assert lead_lag.home_probability("Over 166.5", 0.5, "Atlanta Dream", "Las Vegas Aces") is None
    assert lead_lag.home_probability("A'ja Wilson", 0.6, "Atlanta Dream", "Las Vegas Aces") is None


def test_resampling_keeps_the_last_point_in_a_bucket() -> None:
    """LAST, not mean: the question is when the price ARRIVED at a level,
    and averaging smears an arrival across the interval, biasing every
    measured lag toward zero.
    """
    points = [
        PricePoint(START, 0.50),
        PricePoint(START + timedelta(minutes=1), 0.55),
        PricePoint(START + timedelta(minutes=4), 0.60),
        PricePoint(START + timedelta(minutes=6), 0.70),
    ]
    out = lead_lag.resample_last(points, bucket=timedelta(minutes=5))
    assert [p.probability for p in out] == [0.60, 0.70]


def test_empty_buckets_are_omitted_not_forward_filled() -> None:
    """Forward-filling manufactures a zero change at every quiet minute,
    and those zeros would dominate the correlation -- most minutes have no
    trade at all.
    """
    points = [PricePoint(START, 0.5), PricePoint(START + timedelta(hours=1), 0.6)]
    out = lead_lag.resample_last(points, bucket=timedelta(minutes=5))
    assert len(out) == 2


def test_changes_are_first_differences_stamped_at_the_later_point() -> None:
    out = lead_lag.changes(_series([0.50, 0.55, 0.53]))
    assert [round(v, 4) for _, v in out] == [0.05, -0.02]
    assert out[0][0] == START + timedelta(minutes=5)


def test_a_planted_lead_is_recovered_at_the_right_lag() -> None:
    """The follower is the leader's series shifted 15 minutes later. The
    correlation must peak at +15, and nowhere else.
    """
    moves = [0.50, 0.55, 0.52, 0.60, 0.58, 0.65, 0.61, 0.70]
    leader = lead_lag.changes(_series(moves))
    follower = lead_lag.changes(_series(moves, offset_minutes=15))

    scores = lead_lag.cross_correlate(
        leader, follower, lags_minutes=(-15, 0, 15, 30), tolerance=TOL
    )
    best = max(scores, key=lambda s: s.correlation)
    assert best.lag_minutes == 15
    assert best.correlation > 0.99


def test_independent_series_produce_no_strong_lead() -> None:
    """Guards the method against confirming the hypothesis regardless."""
    leader = lead_lag.changes(_series([0.50, 0.62, 0.41, 0.73, 0.35, 0.68, 0.44, 0.59]))
    follower = lead_lag.changes(_series([0.50, 0.51, 0.49, 0.52, 0.48, 0.53, 0.47, 0.50]))
    scores = lead_lag.cross_correlate(
        leader, follower, lags_minutes=(-30, -15, 0, 15, 30), tolerance=TOL
    )
    assert all(abs(s.correlation) < 0.95 for s in scores)


def test_pairs_outside_the_tolerance_are_dropped_not_zero_filled() -> None:
    """'The follower did not move' and 'we have no observation' are
    different claims and only the first is evidence.
    """
    leader = lead_lag.changes(_series([0.5, 0.6, 0.7]))
    far = lead_lag.changes(_series([0.5, 0.6, 0.7], offset_minutes=600))
    _, pairs = lead_lag.correlate_at_lag(leader, far, lag=timedelta(0), tolerance=TOL)
    assert pairs == 0


def test_a_flat_series_gives_none_rather_than_zero_correlation() -> None:
    """'No linear relationship' and 'one side never moved' are different
    findings; a zero would silently dilute a pooled result.
    """
    leader = lead_lag.changes(_series([0.5, 0.6, 0.7]))
    flat = lead_lag.changes(_series([0.5, 0.5, 0.5]))
    corr, _ = lead_lag.correlate_at_lag(leader, flat, lag=timedelta(0), tolerance=TOL)
    assert corr is None


def test_the_bootstrap_resamples_games_not_observations() -> None:
    """The whole point of the clustered test.

    Twenty copies of one game look like 20 independent games to a pooled
    t-statistic -- which is exactly the trap MODELING_FINDINGS.md records
    (a strategy at t=3.35 on 610 rows that were 65 games, falling to
    t=0.81 when collapsed). Resampling games keeps each game's rows
    together, so a perfectly-correlated single pattern repeated across
    games cannot manufacture confidence beyond the number of games.
    """
    moves = [0.50, 0.55, 0.52, 0.60, 0.58]
    one_game = (lead_lag.changes(_series(moves)), lead_lag.changes(_series(moves)))
    observed, share, games = lead_lag.bootstrap_by_game(
        [one_game] * 20, lag_minutes=0, tolerance=TOL, resamples=200
    )
    assert games == 20
    assert observed is not None and observed > 0.99
    # Every resample draws the same game, so the share below zero is 0 --
    # the test is that `games` counts games, not the 80 paired rows.
    assert share == 0.0


def test_t_statistic_is_none_when_undefined() -> None:
    assert lead_lag.t_statistic(0.5, 2) is None
    assert lead_lag.t_statistic(1.0, 100) is None
    assert lead_lag.t_statistic(0.0, 100) == 0.0
