"""Detection logic for cross-venue divergence.

MODELING_FINDINGS.md records this as the one strategy that survived every
control (+0.97 pts CLV pooled, t=+7.77 Polymarket / +8.28 Kalshi). The
open question is executability, which needs a forward log rather than
another backtest -- this is the detector that feeds it.

The liquidity floor is the load-bearing rule. Without it the first version
of this test reported 71% "arbitrage": $6 and $10 fills sitting at p=0.500
on markets nobody had traded, while the book had the game at 29%. That is
an uninitialised market, not a mispriced book.
"""

from __future__ import annotations

import pytest

from wnba_engine.analysis.divergence import (
    DEFAULT_MIN_VOLUME,
    BookQuote,
    VenuePrice,
    american_to_implied,
    detect_divergences,
)


def _venue(fair_home: float, volume: float = 10_000.0) -> VenuePrice:
    return VenuePrice(
        venue="polymarket", fair_home=fair_home, volume=volume, trade_count=25
    )


class TestAmericanToImplied:
    def test_negative_odds(self) -> None:
        assert american_to_implied(-110) == pytest.approx(0.5238, abs=1e-4)

    def test_positive_odds(self) -> None:
        assert american_to_implied(+150) == pytest.approx(0.4000, abs=1e-4)

    def test_even_money(self) -> None:
        assert american_to_implied(+100) == pytest.approx(0.5)


class TestDetectDivergences:
    def test_no_divergence_when_book_is_dearer_than_the_venue(self) -> None:
        """The normal case: the book's vig makes it more expensive."""
        quotes = (BookQuote(vendor="fanduel", home_odds=-120, away_odds=+100),)
        assert detect_divergences(quotes, _venue(0.50)) == ()

    def test_finds_the_home_side_when_the_book_is_cheaper(self) -> None:
        # -110 implies 52.4%; the venue says home is really 60%.
        quotes = (BookQuote(vendor="fanduel", home_odds=-110, away_odds=-110),)
        (d,) = detect_divergences(quotes, _venue(0.60))
        assert d.side == "home"
        assert d.book_vendor == "fanduel"
        assert d.book_odds == -110
        assert d.edge == pytest.approx(0.60 - 0.5238, abs=1e-4)

    def test_finds_the_away_side(self) -> None:
        quotes = (BookQuote(vendor="fanduel", home_odds=-110, away_odds=-110),)
        (d,) = detect_divergences(quotes, _venue(0.30))
        assert d.side == "away"
        assert d.edge == pytest.approx(0.70 - 0.5238, abs=1e-4)

    def test_takes_the_best_price_across_books(self) -> None:
        """Shopping is not optional -- it is worth ~5 points on its own and
        the divergence is defined against the best available price.
        """
        quotes = (
            BookQuote(vendor="stingy", home_odds=-130, away_odds=+110),
            BookQuote(vendor="generous", home_odds=-105, away_odds=-115),
        )
        (d,) = detect_divergences(quotes, _venue(0.55))
        assert d.book_vendor == "generous"
        assert d.book_odds == -105

    def test_illiquid_venue_is_ignored_entirely(self) -> None:
        """The regression that mattered. A market at p=0.500 on $10 of
        volume against a book at 29% is not a 21% edge.
        """
        quotes = (BookQuote(vendor="fanduel", home_odds=+250, away_odds=-300),)
        thin = VenuePrice(
            venue="polymarket", fair_home=0.500, volume=10.0, trade_count=1
        )
        assert detect_divergences(quotes, thin) == ()

    def test_the_floor_is_configurable_and_inclusive(self) -> None:
        quotes = (BookQuote(vendor="fanduel", home_odds=-110, away_odds=-110),)
        at_floor = VenuePrice(
            venue="kalshi",
            fair_home=0.60,
            volume=float(DEFAULT_MIN_VOLUME),
            trade_count=5,
        )
        assert len(detect_divergences(quotes, at_floor)) == 1
        assert detect_divergences(quotes, at_floor, min_volume=10**9) == ()

    def test_both_sides_cannot_diverge_at_once(self) -> None:
        """A sanity invariant. Book prices include vig so they sum above
        1.0; a venue price sums to exactly 1.0. Both sides being cheap
        would mean the book is giving away money on both, which would be a
        bug in the arithmetic rather than a market event.
        """
        quotes = (BookQuote(vendor="fanduel", home_odds=-110, away_odds=-110),)
        for fair in (0.05, 0.25, 0.5, 0.75, 0.95):
            assert len(detect_divergences(quotes, _venue(fair))) <= 1

    def test_no_quotes_is_not_an_error(self) -> None:
        assert detect_divergences((), _venue(0.60)) == ()

    def test_results_are_immutable(self) -> None:
        quotes = (BookQuote(vendor="fanduel", home_odds=-110, away_odds=-110),)
        (d,) = detect_divergences(quotes, _venue(0.60))
        with pytest.raises(AttributeError):
            d.edge = 0.99  # type: ignore[misc]
