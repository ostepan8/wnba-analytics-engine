"""Unit tests for FEATURE_ROADMAP.md ss8 market steps.

Driven through StaticRowSource so the SQL is not involved -- these are
about the join semantics and the de-vig ordering, both of which shipped
wrong once and were caught only by looking at the built frame.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.frame import FeatureFrame
from wnba_engine.features.source import StaticRowSource
from wnba_engine.features.steps import market_steps

TIP = datetime(2026, 8, 1, 23, 0, tzinfo=UTC)
AS_OF = datetime(2026, 8, 5, tzinfo=UTC)


def _context() -> FeatureContext:
    return FeatureContext(as_of=AS_OF, seasons=(2026,))


def _frame(rows=None) -> FeatureFrame:
    body = tuple(rows or [{"game_id": 1, "start_time": TIP, "team_id": 10}])
    return FeatureFrame.from_rows(
        body,
        columns=("game_id", "start_time", "team_id"),
        as_of_columns=("start_time",),
        event_time_column="start_time",
    )


def _quote(minutes_before: int, vendor: str, home: int, away: int, **extra):
    return {
        "game_id": 1,
        "odds_captured_at": TIP - timedelta(minutes=minutes_before),
        "vendor": vendor,
        "moneyline_home_odds": home,
        "moneyline_away_odds": away,
        "spread_home_value": extra.get("spread"),
        "total_value": extra.get("total"),
    }


def _fill(minutes_before: int, probability: float):
    return {
        "game_id": 1,
        "prediction_traded_at": TIP - timedelta(minutes=minutes_before),
        "prediction_home_probability": probability,
        "prediction_size": 100,
    }


def test_the_consensus_uses_every_book_not_only_those_sharing_an_instant() -> None:
    """The bug this replaced: bucketing by exact captured_at.

    `captured_at` is each BOOK's own last_update, so books almost never
    share an instant -- that version produced a median book_count of 1 and
    an all-null dispersion. The running consensus must see all three books
    here even though every quote has a different timestamp.
    """
    source = StaticRowSource(
        market_odds_rows=[
            _quote(90, "bookA", -120, 100),
            _quote(60, "bookB", -130, 110),
            _quote(30, "bookC", -115, -105),
        ]
    )
    step = market_steps.JoinMarketOddsStep(source=source)
    out = step.apply(_frame(), _context())
    assert out.rows[0]["book_count"] == 3
    assert out.rows[0]["book_home_probability_sd"] is not None


def test_a_book_enters_only_at_its_own_timestamp() -> None:
    """The running consensus must not look ahead: a row tipping between
    two quotes sees only the earlier book.
    """
    source = StaticRowSource(
        market_odds_rows=[_quote(90, "bookA", -120, 100), _quote(30, "bookB", -130, 110)]
    )
    step = market_steps.JoinMarketOddsStep(source=source)
    early = _frame([{"game_id": 1, "start_time": TIP - timedelta(minutes=60), "team_id": 10}])
    assert step.apply(early, _context()).rows[0]["book_count"] == 1
    assert step.apply(_frame(), _context()).rows[0]["book_count"] == 2


def test_the_as_of_anchor_is_written_into_the_row_not_merely_declared() -> None:
    """The bug that made the guard vacuous.

    AsOfJoinStep copies the chosen cells verbatim, so an anchor named only
    in `provenance.as_of_columns` arrives NULL -- and the guard reads a
    null anchor as "no observation" and passes. Both joins in this module
    shipped that way for one build; the frame looked fine and the check
    was checking nothing.
    """
    source = StaticRowSource(market_odds_rows=[_quote(60, "bookA", -120, 100)])
    out = market_steps.JoinMarketOddsStep(source=source).apply(_frame(), _context())
    assert out.rows[0]["odds_captured_at"] == TIP - timedelta(minutes=60)

    fills = StaticRowSource(prediction_market_rows=[_fill(60, 0.56)])
    out = market_steps.JoinPredictionMarketStep(source=fills).apply(_frame(), _context())
    assert out.rows[0]["prediction_traded_at"] == TIP - timedelta(minutes=60)


def test_devigging_happens_per_book_before_averaging() -> None:
    """Averaging raw implied probabilities and de-vigging the average is
    not a probability of anything, and it also destroys the meaning of the
    dispersion column. Two books quoting an identical fair price with
    DIFFERENT margins must agree after de-vig.
    """
    source = StaticRowSource(
        market_odds_rows=[
            _quote(90, "tight", -105, -105),   # 2.4% overround, fair 0.500
            _quote(60, "wide", -130, 110),     # larger margin
        ]
    )
    out = market_steps.JoinMarketOddsStep(source=source).apply(_frame(), _context())
    row = out.rows[0]
    assert row["book_overround"] > 1.0
    # The tight book alone is exactly 0.5; the pair must sit between the
    # two fair prices rather than being dragged by the wider margin.
    assert 0.5 <= row["book_home_probability"] <= 0.56


def test_a_game_with_no_market_gets_nulls_not_a_default() -> None:
    """Left-join semantics. A 0.5 here would assert a coin flip nobody
    quoted, and `book_count` is what keeps the two distinguishable.
    """
    source = StaticRowSource(market_odds_rows=[])
    out = market_steps.JoinMarketOddsStep(source=source).apply(_frame(), _context())
    assert out.rows[0]["book_home_probability"] is None
    assert out.rows[0]["book_count"] is None


def test_the_prediction_trade_count_is_running_not_final() -> None:
    """A row joined mid-series must report how many fills preceded IT.
    Reporting the game's eventual total would be a fact from the future.
    """
    source = StaticRowSource(
        prediction_market_rows=[_fill(90, 0.50), _fill(60, 0.55), _fill(30, 0.60)]
    )
    step = market_steps.JoinPredictionMarketStep(source=source)
    mid = _frame([{"game_id": 1, "start_time": TIP - timedelta(minutes=45), "team_id": 10}])
    assert step.apply(mid, _context()).rows[0]["prediction_trade_count"] == 2
    assert step.apply(_frame(), _context()).rows[0]["prediction_trade_count"] == 3


def test_divergence_is_prediction_minus_books() -> None:
    """Sign convention: positive means Polymarket is higher on the home
    side. On 2026-08-03 that reached +4.3 points on a live game, which is
    what motivated analysis/lead_lag.py.
    """
    row = market_steps.MarketDivergenceStep().transform(
        {
            "book_home_probability": 0.522,
            "prediction_home_probability": 0.565,
            "book_opening_home_probability": 0.500,
            "prediction_opening_home_probability": 0.535,
        },
        _context(),
    )
    assert row["market_divergence"] == pytest.approx(0.043)
    assert row["book_line_movement"] == pytest.approx(0.022)
    assert row["prediction_line_movement"] == pytest.approx(0.030)
    assert row["market_agreement_rank"] == pytest.approx(0.043)


def test_divergence_is_null_when_either_venue_is_missing() -> None:
    """Polymarket covers 2025 onward; the books go back to 2022. Treating
    a missing venue as agreement would assert the two matched on every
    pre-2025 game.
    """
    row = market_steps.MarketDivergenceStep().transform(
        {"book_home_probability": 0.52, "prediction_home_probability": None},
        _context(),
    )
    assert row["market_divergence"] is None
    assert row["market_agreement_rank"] is None


def test_the_median_is_used_for_spreads_so_one_off_market_book_cannot_drag_it() -> None:
    """Concretely: on 2026-08-03 Fanatics alone posted ATL -1.0 while ten
    books sat at -2.5. A mean would move the consensus off the key number
    on the strength of one outlier.
    """
    source = StaticRowSource(
        market_odds_rows=[
            _quote(90, "a", -120, 100, spread=-2.5),
            _quote(80, "b", -120, 100, spread=-2.5),
            _quote(70, "c", -120, 100, spread=-1.0),
        ]
    )
    out = market_steps.JoinMarketOddsStep(source=source).apply(_frame(), _context())
    assert out.rows[0]["book_spread_home"] == -2.5
