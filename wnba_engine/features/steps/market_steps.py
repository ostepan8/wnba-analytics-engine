"""Market-derived features (FEATURE_ROADMAP.md ss8).

**Read the roadmap's warning before using these.** The line is the best
single forecast available, so a frame containing it will look brilliant and
teach nothing about basketball. They live in their own strategy
(`team_market`) precisely so they cannot leak into a "pure basketball"
model by accident.

Two as-of joins bring outside data in, and everything else is derived
row-locally from what they added:

| step | question |
|---|---|
| `JoinMarketOddsStep` | what did the books think, before this game |
| `JoinPredictionMarketStep` | what did Polymarket think, before this game |
| `MarketDivergenceStep` | do the two venues disagree |

The joins are per ROW, not per frame. `AsOfJoinStep`'s docstring records the
concrete leak the per-frame version produced against `team_standings_history`
-- a full-season frame handing a May game July's data -- and a market series
is far denser than standings, so the same mistake here would be larger.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from wnba_engine.analysis.clv import remove_vig
from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import StepContractError
from wnba_engine.features.frame import Row
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.source import FeatureRowSource
from wnba_engine.features.step import AsOfJoinStep, RowMapStep

#: Columns `JoinMarketOddsStep` adds.
MARKET_ODDS_COLUMNS: tuple[str, ...] = (
    "book_home_probability",
    "book_home_probability_sd",
    "book_spread_home",
    "book_total",
    "book_count",
    "book_overround",
    "book_opening_home_probability",
)

#: Columns `JoinPredictionMarketStep` adds.
PREDICTION_MARKET_COLUMNS: tuple[str, ...] = (
    "prediction_home_probability",
    "prediction_trade_count",
    "prediction_opening_home_probability",
)


@dataclass(frozen=True, slots=True)
class JoinMarketOddsStep(AsOfJoinStep):
    """Consensus sportsbook view as it stood before each game.

    DE-VIGS PER BOOK, THEN AGGREGATES -- never the other way round. Each
    book prices its own margin into both sides, so averaging raw implied
    probabilities across books and de-vigging the average produces a number
    that is not a probability of anything. Doing it in the correct order
    also makes `book_home_probability_sd` meaningful: genuine disagreement
    between books rather than a mix of disagreement and differing margins.

    `book_opening_home_probability` is the FIRST quote observed for that
    game, carried on every later observation. It is knowable at any instant
    after it happened, so it introduces no leak -- and it is what makes
    line movement expressible row-locally without a second join.

    Nulls are the truthful answer for any game the books did not price.
    `book_count` keeps "no market" distinguishable from "a market at 0.5".
    """

    source: FeatureRowSource
    step_name: str = "join_market_odds"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.JOIN,
            adds_columns=(*MARKET_ODDS_COLUMNS, "odds_captured_at"),
            as_of_columns=("odds_captured_at",),
            source_tables=("sportsbook_game_odds",),
        )

    def observations(
        self, context: FeatureContext
    ) -> dict[tuple[object, ...], list[tuple[datetime, Row]]]:
        """A RUNNING consensus: each book's latest quote as of each instant.

        The obvious implementation -- bucket rows by exact `captured_at` and
        average the books sharing that timestamp -- is wrong for this table
        and quietly so. `captured_at` is each BOOK's own `last_update`, so
        two books almost never share an instant: measured against this
        database, that version produced a median `book_count` of 1, i.e. a
        "consensus" that was usually one book, with a dispersion of null.

        So the walk is stateful. Quotes are consumed in time order, each
        one replacing that book's previous contribution, and a consensus is
        emitted after every update from whatever every book last said. That
        is what a bettor could actually have seen at that moment, and it
        cannot look ahead: a book's quote enters only at its own timestamp.
        """
        by_game: dict[object, list[tuple[datetime, Row]]] = {}
        for row in self.source.market_odds(context):
            captured_at = row["odds_captured_at"]
            if not isinstance(captured_at, datetime):
                raise StepContractError(
                    f"market odds row has a non-datetime captured_at: {captured_at!r}"
                )
            by_game.setdefault(row["game_id"], []).append((captured_at, row))

        series: dict[tuple[object, ...], list[tuple[datetime, Row]]] = {}
        for game_id, quotes in by_game.items():
            quotes.sort(key=lambda pair: (pair[0], str(pair[1].get("vendor"))))
            latest_by_book: dict[object, Row] = {}
            observations: list[tuple[datetime, Row]] = []
            opening: float | None = None
            for captured_at, quote in quotes:
                latest_by_book[quote.get("vendor")] = quote
                cells = _consensus(list(latest_by_book.values()))
                cells["odds_captured_at"] = captured_at
                if opening is None:
                    opening = cells.get("book_home_probability")  # type: ignore[assignment]
                cells["book_opening_home_probability"] = opening
                observations.append((captured_at, cells))
            series[(game_id,)] = observations
        return series

    def key_for(self, row: Row) -> tuple[object, ...]:
        return (row.get("game_id"),)


def _consensus(quotes: Sequence[Row]) -> dict[str, object]:
    """De-vig every book's pair, then average."""
    probabilities: list[float] = []
    overrounds: list[float] = []
    spreads: list[float] = []
    totals: list[float] = []
    for quote in quotes:
        home = quote.get("moneyline_home_odds")
        away = quote.get("moneyline_away_odds")
        if home is None or away is None:
            continue
        prices = remove_vig(int(home), int(away))  # type: ignore[arg-type]
        probabilities.append(prices.over)
        overrounds.append(prices.overround)
        spread = quote.get("spread_home_value")
        if spread is not None:
            spreads.append(float(spread))  # type: ignore[arg-type]
        total = quote.get("total_value")
        if total is not None:
            totals.append(float(total))  # type: ignore[arg-type]
    return {
        "book_home_probability": _mean(probabilities),
        "book_home_probability_sd": _sd(probabilities),
        "book_spread_home": _median(spreads),
        "book_total": _median(totals),
        "book_count": len(probabilities),
        "book_overround": _mean(overrounds),
        "book_opening_home_probability": None,  # filled in by the caller
    }


@dataclass(frozen=True, slots=True)
class JoinPredictionMarketStep(AsOfJoinStep):
    """Polymarket's view as it stood before each game, from FILLS.

    FEATURE_ROADMAP.md marked this "only 2026-07 onward -- unusable
    historically" because `market_price_snapshots` begins when the capture
    host did. This reads `polymarket_trades` instead, which goes back to
    2024-09, so the historical limitation no longer applies.

    `traded_at` is the anchor, and it is a better one than any `captured_at`
    in this schema: it records when the price EXISTED, not when we happened
    to be polling. Nothing about it depends on our uptime.

    No de-vig: Polymarket's two outcomes are complementary shares of one
    dollar, so a fill price is already a probability. That is also why this
    is arguably the cleaner fair-value reference of the two venues.
    """

    source: FeatureRowSource
    step_name: str = "join_prediction_market"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(
            kind=StepKind.JOIN,
            adds_columns=(*PREDICTION_MARKET_COLUMNS, "prediction_traded_at"),
            as_of_columns=("prediction_traded_at",),
            source_tables=("polymarket_trades",),
        )

    def observations(
        self, context: FeatureContext
    ) -> dict[tuple[object, ...], list[tuple[datetime, Row]]]:
        series: dict[tuple[object, ...], list[tuple[datetime, Row]]] = {}
        counts: dict[tuple[object, ...], int] = {}
        for row in self.source.prediction_market_prices(context):
            traded_at = row["prediction_traded_at"]
            if not isinstance(traded_at, datetime):
                raise StepContractError(
                    f"prediction market row has a non-datetime traded_at: {traded_at!r}"
                )
            key = (row["game_id"],)
            counts[key] = counts.get(key, 0) + 1
            series.setdefault(key, []).append(
                (
                    traded_at,
                    {
                        # The anchor MUST be in the cells, not merely
                        # declared. AsOfJoinStep copies the chosen cells
                        # verbatim, so an anchor that is only named in
                        # provenance arrives NULL -- and the guard treats a
                        # null anchor as "no observation" and passes,
                        # making the whole check vacuous. Both joins in
                        # this module shipped that way for one build.
                        "prediction_traded_at": traded_at,
                        "prediction_home_probability": float(
                            row["prediction_home_probability"]  # type: ignore[arg-type]
                        ),
                        # Running count, so a row joined mid-series reports
                        # how many fills preceded IT rather than how many
                        # the game eventually saw -- the latter would be a
                        # fact from the future.
                        "prediction_trade_count": counts[key],
                        "prediction_opening_home_probability": None,
                    },
                )
            )
        for observations in series.values():
            observations.sort(key=lambda pair: pair[0])
            opening = observations[0][1]["prediction_home_probability"]
            for _, cells in observations:
                cells["prediction_opening_home_probability"] = opening
        return series

    def key_for(self, row: Row) -> tuple[object, ...]:
        return (row.get("game_id"),)


@dataclass(frozen=True, slots=True)
class MarketDivergenceStep(RowMapStep):
    """Where the two venues disagree, and how far each has moved.

    Row-local and therefore incapable of leaking: every column it reads was
    already placed in the frame by an as-of join that carried its own
    anchor.

    `market_divergence` is Polymarket minus the books, both as P(home).
    Positive means the prediction market is higher on the home side. On
    2026-08-03 that number reached +4.3 points on a live game while eleven
    books sat 4.3 apart from Polymarket's mid -- which is the observation
    that motivated `analysis/lead_lag.py`.

    Movement columns are current minus opening for each venue separately.
    Kept apart rather than differenced against each other because "the line
    moved" and "the venues disagree" are different signals and a model
    should be able to use one without the other.
    """

    step_name: str = "market_divergence"

    @property
    def name(self) -> str:
        return self.step_name

    @property
    def output_columns(self) -> tuple[str, ...]:
        return (
            "market_divergence",
            "book_line_movement",
            "prediction_line_movement",
            "market_agreement_rank",
        )

    @property
    def provenance(self) -> StepProvenance:
        return StepProvenance(kind=StepKind.ROW_LOCAL, adds_columns=self.output_columns)

    def transform(self, row: Row, context: FeatureContext) -> Row:
        del context
        book = _as_float(row.get("book_home_probability"))
        prediction = _as_float(row.get("prediction_home_probability"))
        book_open = _as_float(row.get("book_opening_home_probability"))
        prediction_open = _as_float(row.get("prediction_opening_home_probability"))
        divergence = (
            None if book is None or prediction is None else prediction - book
        )
        return {
            "market_divergence": divergence,
            "book_line_movement": (
                None if book is None or book_open is None else book - book_open
            ),
            "prediction_line_movement": (
                None
                if prediction is None or prediction_open is None
                else prediction - prediction_open
            ),
            # Absolute disagreement, kept separately because a model may
            # care that the venues disagree without caring which way.
            "market_agreement_rank": None if divergence is None else abs(divergence),
        }


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    """Median rather than mean for spreads and totals.

    These are quoted on a half-point grid and one book posting an off-market
    number (Fanatics was alone at ATL -1.0 while ten books sat at -2.5 on
    2026-08-03) should not drag the consensus off the key number.
    """
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _sd(values: Sequence[float]) -> float | None:
    """Sample SD; None below two books, because one book has no dispersion."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


__all__ = [
    "MARKET_ODDS_COLUMNS",
    "PREDICTION_MARKET_COLUMNS",
    "JoinMarketOddsStep",
    "JoinPredictionMarketStep",
    "MarketDivergenceStep",
]
