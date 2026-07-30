"""Closing line value: did you get a better price than the market settled on?

WHY THIS AND NOT WIN RATE. The closing line is the most efficient price a
betting market produces -- it has absorbed every injury report, lineup
change, and dollar of sharp money. Measuring a prediction against the
CLOSE rather than against the outcome separates skill from variance: a
pick that beat the closing price was good even if it lost, and a pick
that lost to the close was bad even if it won. Outcome-based evaluation
needs thousands of settled bets to say anything; CLV says it immediately,
and needs no bet to be placed at all.

That framing is standard among practitioners, and worth one caveat: the
most-cited evidence for "positive CLV implies profit" is sportsbook-
published rather than peer-reviewed. Treat it as a well-supported working
principle, not a proven theorem.

HOW IT IS COMPUTED HERE. A prop has two sides, and the prices on both
include the bookmaker's margin. Comparing raw American odds would measure
the vig as much as the market's opinion, so both sides are converted to
implied probability and normalized to sum to 1 (the standard
multiplicative de-vig). CLV is then:

    clv = novig_probability_at_close(side) - novig_probability_when_bet(side)

Positive means the market moved TOWARD your side after you took it: you
bought at a probability the market later judged too low. Expressed in
probability points, so +0.02 means "two points of edge against the
closing consensus".

WHAT THIS FILE DELIBERATELY DOES NOT DO. When the LINE moves -- Under 8.5
becoming Under 7.5 -- your bet and the closing bet are not the same
wager, and differencing their probabilities silently compares apples to
oranges. Verified on this database: 89.1% of WNBA prop lines never move
between first and last capture, while 45.7% see a price change, so the
price-only comparison covers the overwhelming majority honestly. The rest
are reported as `line_moved` and excluded from the CLV average rather
than being fudged into it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SIDE_OVER = "over"
SIDE_UNDER = "under"


def american_to_implied(odds: int) -> float:
    """American odds -> raw implied probability (vig still included).

    -150 means risking 150 to win 100, i.e. the book is pricing a 60%
    chance; +150 means risking 100 to win 150, i.e. 40%.
    """
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def american_to_profit(odds: int) -> float:
    """Profit per 1 unit staked on a winning bet."""
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    return odds / 100.0 if odds > 0 else 100.0 / -odds


@dataclass(frozen=True, slots=True)
class NoVigPrices:
    """Both sides of one market with the bookmaker's margin removed."""

    over: float
    under: float
    overround: float  # raw probabilities summed; 1.0 would be a zero-margin book

    def probability(self, side: str) -> float:
        if side == SIDE_OVER:
            return self.over
        if side == SIDE_UNDER:
            return self.under
        raise ValueError(f"side must be {SIDE_OVER!r} or {SIDE_UNDER!r}, got {side!r}")


def remove_vig(over_odds: int, under_odds: int) -> NoVigPrices:
    """De-vig a two-sided market by proportional normalization.

    The two raw implied probabilities sum to more than 1 -- that excess IS
    the bookmaker's margin. Scaling both down by the same factor is the
    standard "multiplicative" method. It assumes the margin is spread
    proportionally across both sides, which is not exactly true (books
    typically load more margin onto the side the public prefers), but the
    alternatives require assumptions this data cannot support, and the
    error is small relative to the CLV signal being measured.
    """
    raw_over = american_to_implied(over_odds)
    raw_under = american_to_implied(under_odds)
    overround = raw_over + raw_under
    if overround <= 0:
        raise ValueError("implied probabilities must be positive")
    return NoVigPrices(
        over=raw_over / overround, under=raw_under / overround, overround=overround
    )


@dataclass(frozen=True, slots=True)
class ClvResult:
    """One pick scored against the closing price.

    `clv` is None when it could not be computed honestly -- see
    `line_moved`. Callers must not treat that as zero.
    """

    side: str
    bet_line: float
    close_line: float
    bet_probability: float
    close_probability: float
    clv: float | None
    line_moved: bool
    bet_captured_at: datetime
    close_captured_at: datetime

    @property
    def beat_the_close(self) -> bool:
        """True only for a computable, strictly positive CLV."""
        return self.clv is not None and self.clv > 0


def score_pick(
    *,
    side: str,
    bet_line: float,
    bet_over_odds: int,
    bet_under_odds: int,
    bet_captured_at: datetime,
    close_line: float,
    close_over_odds: int,
    close_under_odds: int,
    close_captured_at: datetime,
) -> ClvResult:
    """Score one pick against the closing price of the same market.

    Both prices are de-vigged before differencing, so this measures the
    market's change of opinion rather than the bookmaker's margin.
    """
    if side not in (SIDE_OVER, SIDE_UNDER):
        raise ValueError(f"side must be {SIDE_OVER!r} or {SIDE_UNDER!r}, got {side!r}")

    bet_prices = remove_vig(bet_over_odds, bet_under_odds)
    close_prices = remove_vig(close_over_odds, close_under_odds)
    bet_probability = bet_prices.probability(side)
    close_probability = close_prices.probability(side)

    line_moved = bet_line != close_line
    return ClvResult(
        side=side,
        bet_line=bet_line,
        close_line=close_line,
        bet_probability=bet_probability,
        close_probability=close_probability,
        # A moved line makes these two different wagers. Reporting None
        # rather than a number is the whole point: a silently wrong CLV
        # is worse than a missing one, because it still gets averaged.
        clv=None if line_moved else close_probability - bet_probability,
        line_moved=line_moved,
        bet_captured_at=bet_captured_at,
        close_captured_at=close_captured_at,
    )


@dataclass(frozen=True, slots=True)
class ClvSummary:
    picks: int
    scored: int  # picks with a computable CLV
    line_moved: int
    mean_clv: float | None
    beat_close: int
    beat_close_rate: float | None

    @property
    def unscored_share(self) -> float:
        return self.line_moved / self.picks if self.picks else 0.0


def summarize(results: tuple[ClvResult, ...]) -> ClvSummary:
    """Aggregate scored picks, keeping the unscorable ones visible.

    `line_moved` picks are counted but excluded from the mean, and the
    count is reported so a caller can see how much of the sample was
    dropped instead of inferring it from a suspiciously round number.
    """
    scored = tuple(r for r in results if r.clv is not None)
    moved = len(results) - len(scored)
    if not scored:
        return ClvSummary(
            picks=len(results),
            scored=0,
            line_moved=moved,
            mean_clv=None,
            beat_close=0,
            beat_close_rate=None,
        )
    beat = sum(1 for r in scored if r.beat_the_close)
    return ClvSummary(
        picks=len(results),
        scored=len(scored),
        line_moved=moved,
        mean_clv=sum(r.clv for r in scored if r.clv is not None) / len(scored),
        beat_close=beat,
        beat_close_rate=beat / len(scored),
    )
