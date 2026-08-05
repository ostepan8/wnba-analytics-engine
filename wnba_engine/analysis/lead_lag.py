"""Does one venue's price move before the other's?

MODELING_FINDINGS.md lists this as the one hypothesis never properly TESTED
rather than refuted. Everything else tried against this data lost to the
closing line; cross-venue lead-lag was never measured because the only
prediction-market data was 30-minute quote snapshots, and a 16-29 minute lag
is invisible at that cadence -- you cannot see a lag shorter than your
sampling interval.

`polymarket_trades` removes that limitation: fills carry exact timestamps,
and `sportsbook_game_odds.captured_at` is each book's own `last_update`.
Both sides are now event-timed.

Everything here is PURE -- series in, statistics out, no database. The
pipeline layer assembles the series (see pipeline/lead_lag_report.py).

WHAT THIS CAN AND CANNOT SHOW. A positive peak means Polymarket moves first
in this sample. It does NOT mean the move is tradeable: the books' quotes
must still be gettable at the moment of the signal, and MODELING_FINDINGS.md
already records one case (CLV without profit) where a real, statistically
solid price-direction signal produced negative ROI anyway. Treat a lead as a
necessary condition for an edge, never a sufficient one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Below this the "book" is a placeholder rather than a price. Chosen from
#: the archive rather than taste: tonight's Polymarket totals carried
#: 35-cent spreads on $85 of volume, and quotes like that move for reasons
#: that have nothing to do with information.
MIN_SPREAD_VOLUME = 100.0


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One observation of home-win probability from one venue."""

    at: datetime
    probability: float


@dataclass(frozen=True, slots=True)
class LagCorrelation:
    lag_minutes: int
    correlation: float
    pairs: int


@dataclass(frozen=True, slots=True)
class LeadLagResult:
    """Cross-correlation of the two venues' CHANGES across lags.

    `best_lag_minutes` is the lag maximising |correlation|. Positive means
    a Polymarket change is followed by a sportsbook change that many
    minutes later -- Polymarket leads. Negative means the reverse.
    """

    games: int
    observations: int
    by_lag: tuple[LagCorrelation, ...]
    best_lag_minutes: int | None
    best_correlation: float | None

    @property
    def polymarket_leads(self) -> bool | None:
        if self.best_lag_minutes is None:
            return None
        return self.best_lag_minutes > 0


def home_probability(
    outcome: str, price: float, home_team: str, away_team: str
) -> float | None:
    """A fill's price expressed as P(home wins), or None if it is neither side.

    Polymarket states the outcome as a team NAME, which is why this can be
    exact rather than inferred -- `market_price_snapshots` has no recorded
    side for two-way markets at all. Roughly 19% of linked fills name
    neither team (props and derivatives on the same game) and correctly
    return None rather than being forced onto a side.
    """
    if outcome == home_team:
        return price
    if outcome == away_team:
        return 1.0 - price
    return None


def resample_last(points: Sequence[PricePoint], *, bucket: timedelta) -> list[PricePoint]:
    """Last observation in each bucket, on a fixed grid.

    LAST, not mean: a lead-lag test asks when the price ARRIVED at a level,
    and averaging within a bucket smears an arrival across the whole
    interval, which biases every measured lag toward zero.

    Empty buckets are omitted rather than forward-filled. Forward-filling
    would manufacture a "change of zero" at every quiet minute, and those
    zeros dominate the correlation -- most minutes have no trade.
    """
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p.at)
    seconds = bucket.total_seconds()
    buckets: dict[int, PricePoint] = {}
    for point in ordered:
        key = int(point.at.timestamp() // seconds)
        buckets[key] = point  # later point in the same bucket wins
    return [buckets[key] for key in sorted(buckets)]


def changes(points: Sequence[PricePoint]) -> list[tuple[datetime, float]]:
    """Consecutive first differences, timestamped at the LATER point.

    Differences rather than levels. Two price series for the same game are
    both near the same number all night, so their levels correlate at ~0.99
    regardless of who moved first -- a correlation of levels measures that
    they describe the same game, not that one leads.
    """
    out: list[tuple[datetime, float]] = []
    for earlier, later in zip(points, points[1:], strict=False):
        out.append((later.at, later.probability - earlier.probability))
    return out


def correlate_at_lag(
    leader: Sequence[tuple[datetime, float]],
    follower: Sequence[tuple[datetime, float]],
    *,
    lag: timedelta,
    tolerance: timedelta,
) -> tuple[float | None, int]:
    """Pearson correlation of leader changes against follower changes `lag` later.

    Each leader change is paired with the follower change closest to
    (leader time + lag), within `tolerance`. Unpaired leader changes are
    dropped rather than zero-filled: "the follower did not move" and "we
    have no observation of the follower" are different claims, and only the
    first is evidence.
    """
    if not leader or not follower:
        return None, 0
    follower_times = [t for t, _ in follower]
    xs: list[float] = []
    ys: list[float] = []
    for at, delta in leader:
        target = at + lag
        index = _closest(follower_times, target)
        if index is None:
            continue
        if abs((follower_times[index] - target).total_seconds()) > tolerance.total_seconds():
            continue
        xs.append(delta)
        ys.append(follower[index][1])
    return _pearson(xs, ys), len(xs)


def cross_correlate(
    leader: Sequence[tuple[datetime, float]],
    follower: Sequence[tuple[datetime, float]],
    *,
    lags_minutes: Sequence[int],
    tolerance: timedelta,
) -> tuple[LagCorrelation, ...]:
    results: list[LagCorrelation] = []
    for minutes in lags_minutes:
        corr, pairs = correlate_at_lag(
            leader, follower, lag=timedelta(minutes=minutes), tolerance=tolerance
        )
        if corr is not None:
            results.append(LagCorrelation(minutes, corr, pairs))
    return tuple(results)


def summarise(
    per_game: Sequence[tuple[Sequence[tuple[datetime, float]], Sequence[tuple[datetime, float]]]],
    *,
    lags_minutes: Sequence[int],
    tolerance: timedelta,
    min_pairs: int = 30,
) -> LeadLagResult:
    """Pool every game's paired changes, then correlate once per lag.

    POOLED, not averaged across per-game correlations. MODELING_FINDINGS.md
    records the correlation trap this repo already paid for once: a totals
    strategy showed +12.72% at t=3.35 on 610 rows that were really 65
    games, and collapsing to one row per game took t to 0.81. Averaging
    per-game correlations here would repeat the mistake in the other
    direction -- a game with four fills would count as much as one with
    four hundred. Pooling the observations and reporting the pair count
    lets a reader judge the real sample size.
    """
    pooled: dict[int, tuple[list[float], list[float]]] = {m: ([], []) for m in lags_minutes}
    games = 0
    for leader, follower in per_game:
        if not leader or not follower:
            continue
        games += 1
        follower_times = [t for t, _ in follower]
        for minutes in lags_minutes:
            target_delta = timedelta(minutes=minutes)
            xs, ys = pooled[minutes]
            for at, delta in leader:
                target = at + target_delta
                index = _closest(follower_times, target)
                if index is None:
                    continue
                gap = abs((follower_times[index] - target).total_seconds())
                if gap > tolerance.total_seconds():
                    continue
                xs.append(delta)
                ys.append(follower[index][1])

    by_lag: list[LagCorrelation] = []
    for minutes in lags_minutes:
        xs, ys = pooled[minutes]
        if len(xs) < min_pairs:
            continue
        corr = _pearson(xs, ys)
        if corr is not None:
            by_lag.append(LagCorrelation(minutes, corr, len(xs)))

    best = max(by_lag, key=lambda c: abs(c.correlation), default=None)
    return LeadLagResult(
        games=games,
        observations=sum(c.pairs for c in by_lag),
        by_lag=tuple(by_lag),
        best_lag_minutes=best.lag_minutes if best else None,
        best_correlation=best.correlation if best else None,
    )


def _closest(times: Sequence[datetime], target: datetime) -> int | None:
    """Index of the nearest timestamp by binary search."""
    if not times:
        return None
    low, high = 0, len(times) - 1
    if target <= times[0]:
        return 0
    if target >= times[high]:
        return high
    while low < high - 1:
        mid = (low + high) // 2
        if times[mid] < target:
            low = mid
        else:
            high = mid
    before = (target - times[low]).total_seconds()
    after = (times[high] - target).total_seconds()
    return low if before <= after else high


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson r, or None when it is undefined.

    None rather than 0.0 for a constant series: "no linear relationship"
    and "one side never moved" are different findings, and a zero here
    would silently dilute a pooled result.
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return sxy / math.sqrt(sxx * syy)


def bootstrap_by_game(
    per_game: Sequence[tuple[Sequence[tuple[datetime, float]], Sequence[tuple[datetime, float]]]],
    *,
    lag_minutes: int,
    tolerance: timedelta,
    resamples: int = 2000,
    seed: int = 20260803,
) -> tuple[float | None, float | None, int]:
    """(observed r, share of resamples with r <= 0, games) -- clustered by GAME.

    The plain t-statistic on a pooled correlation is WRONG here and wrong in
    the specific way MODELING_FINDINGS.md already paid to learn. A totals
    strategy once reported +12.72% at t=3.35 on 610 rows that were really 65
    games; collapsing to one row per game took t to 0.81. This test has the
    same shape -- ~750 paired observations drawn from ~200 games -- so the
    nominal t overstates significance by roughly the square root of the
    within-game clustering.

    Resampling GAMES with replacement (a block bootstrap) keeps each game's
    observations together, so the resampled distribution reflects the number
    of independent units actually available rather than the number of rows.

    Returns the one-sided share of resamples at or below zero: the
    hypothesis is directional ("this venue leads"), so a two-sided test
    would be answering a question nobody asked.
    """
    import random

    paired: list[tuple[list[float], list[float]]] = []
    for leader, follower in per_game:
        if not leader or not follower:
            continue
        follower_times = [t for t, _ in follower]
        xs: list[float] = []
        ys: list[float] = []
        for at, delta in leader:
            target = at + timedelta(minutes=lag_minutes)
            index = _closest(follower_times, target)
            if index is None:
                continue
            if abs((follower_times[index] - target).total_seconds()) > tolerance.total_seconds():
                continue
            xs.append(delta)
            ys.append(follower[index][1])
        if xs:
            paired.append((xs, ys))
    if len(paired) < 2:
        return None, None, len(paired)

    observed = _pearson(
        [x for xs, _ in paired for x in xs], [y for _, ys in paired for y in ys]
    )
    if observed is None:
        return None, None, len(paired)

    rng = random.Random(seed)
    below = 0
    counted = 0
    for _ in range(resamples):
        picks = [paired[rng.randrange(len(paired))] for _ in range(len(paired))]
        r = _pearson(
            [x for xs, _ in picks for x in xs], [y for _, ys in picks for y in ys]
        )
        if r is None:
            continue
        counted += 1
        if r <= 0:
            below += 1
    share = below / counted if counted else None
    return observed, share, len(paired)


def t_statistic(correlation: float, pairs: int) -> float | None:
    """Two-sided t for r != 0, with pairs-2 degrees of freedom.

    Reported alongside every correlation because at these sample sizes an
    r of 0.02 is "significant" and meaningless, and the reader needs both
    numbers to see that.
    """
    if pairs < 3 or abs(correlation) >= 1.0:
        return None
    return correlation * math.sqrt((pairs - 2) / (1 - correlation**2))
