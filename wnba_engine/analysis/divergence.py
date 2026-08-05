"""Cross-venue divergence detection.

A sportsbook price carries vig, so the two sides sum to more than 1.0. A
prediction-market price does not -- Polymarket and Kalshi quote a fair
probability. When the best book price for a side, vig included, is STILL
cheaper than the prediction market's fair probability for that side, the
book is offering that outcome below its market value.

That comparison needs no forecast, which is the entire reason it is worth
anything: MODELING_FINDINGS.md records 13 forecasting hypotheses that
failed and one structural one that did not. Measured at +1.07 points of
CLV over a matched control on Polymarket (t=+7.77) and +0.76 on Kalshi
(t=+8.28), against a control showing that merely picking the cheapest book
price explains only 0.08 of it.

This module is pure. It knows nothing about the database, so the rules can
be tested against hand-written prices rather than against whatever the
market happened to do.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Minimum prediction-market volume, in the venue's own units (dollars for
#: Polymarket, contracts for Kalshi), inside the lookback window before a
#: quote counts as priced at all.
#:
#: This floor is the difference between a finding and an artifact. Without
#: it the first pass of this analysis reported divergences up to 71%, all
#: of them $6 and $10 fills resting at p=0.500 on markets nobody had
#: traded, while the book had the game at 29%. That is an uninitialised
#: market being read as a mispriced book. With the floor in place the
#: divergence rate RISES with liquidity (12.2% of moments at any volume,
#: 31.0% above $20,000), which is the opposite of what noise does and is
#: the main reason to believe the effect is real.
DEFAULT_MIN_VOLUME = 1_000.0


def american_to_implied(odds: int) -> float:
    """Implied probability of American odds, vig included.

    Deliberately NOT de-vigged. The number we need is what the bet costs,
    not what the book thinks -- the whole comparison is "is the price I
    actually pay below the venue's fair value".
    """
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


@dataclass(frozen=True, slots=True)
class BookQuote:
    """One sportsbook's two-sided moneyline at a moment."""

    vendor: str
    home_odds: int
    away_odds: int


@dataclass(frozen=True, slots=True)
class VenuePrice:
    """A prediction market's fair price, size-weighted over a window.

    `fair_home` is the probability of the HOME team winning, so the away
    side is its complement. Both venues are normalised to that convention
    upstream: Polymarket by matching the outcome string to a team name,
    Kalshi by the team abbreviation in the ticker suffix.
    """

    venue: str
    fair_home: float
    volume: float
    trade_count: int


@dataclass(frozen=True, slots=True)
class Divergence:
    """A book price below the venue's fair value for the same side."""

    side: str
    book_vendor: str
    book_odds: int
    book_implied: float
    venue_fair: float
    edge: float


def detect_divergences(
    quotes: Sequence[BookQuote],
    venue: VenuePrice,
    *,
    min_volume: float = DEFAULT_MIN_VOLUME,
) -> tuple[Divergence, ...]:
    """Best book price per side against the venue's fair price.

    Returns at most one divergence per side, and in practice at most one
    overall: book prices sum above 1.0 while the venue sums to exactly
    1.0, so both sides being underpriced is arithmetically impossible
    rather than merely unlikely.
    """
    if not quotes or venue.volume < min_volume:
        return ()

    fair_away = 1.0 - venue.fair_home
    # Best price for the bettor is the highest American odds, which is the
    # lowest implied probability -- the cheapest way to own the outcome.
    best_home = max(quotes, key=lambda q: q.home_odds)
    best_away = max(quotes, key=lambda q: q.away_odds)

    found: list[Divergence] = []
    for side, quote, odds, fair in (
        ("home", best_home, best_home.home_odds, venue.fair_home),
        ("away", best_away, best_away.away_odds, fair_away),
    ):
        implied = american_to_implied(odds)
        edge = fair - implied
        if edge > 0:
            found.append(
                Divergence(
                    side=side,
                    book_vendor=quote.vendor,
                    book_odds=odds,
                    book_implied=implied,
                    venue_fair=fair,
                    edge=edge,
                )
            )
    return tuple(found)
