"""Forward log of cross-venue divergences, and its two grading passes.

Answers the one question MODELING_FINDINGS.md cannot answer from history:
the effect is established (+0.97 pts CLV pooled, t=+7.77 / +8.28 on two
independent venues) but every divergence in the backtest was seen up to an
hour late, because historical sportsbook captures are ~60 minutes apart.
Whether the price is still there when you could act on it needs a log
written at the capture cadence, not another backtest.

Three entry points, deliberately separate:

  log_divergences   -- detect and record, meant to run right after each
                       focused odds capture (every 2 minutes)
  recheck_prices    -- did that price survive to the next quote?  This is
                       the executability answer.
  grade_closings    -- closing line and outcome, once the game is final.

Read-only price analysis. Nothing here places or facilitates a bet; see
ROADMAP.md's non-goals.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from wnba_engine.analysis.divergence import (
    DEFAULT_MIN_VOLUME,
    BookQuote,
    VenuePrice,
    american_to_implied,
    detect_divergences,
)
from wnba_engine.db.pool import Database
from wnba_engine.models.divergence import DivergenceObservation
from wnba_engine.repositories import divergence_repo

logger = logging.getLogger(__name__)

#: How far ahead of tip a game is worth watching. Matches the focused
#: capture's window so the two agents look at the same games.
DEFAULT_WINDOW = timedelta(hours=6)

#: Trailing window over which the venue price is size-weighted. Short
#: enough to be a current price, long enough that a quiet minute does not
#: erase the market.
DEFAULT_LOOKBACK = timedelta(minutes=10)

_LATEST_QUOTES = """
SELECT DISTINCT ON (o.game_id, o.vendor)
       o.game_id, o.vendor, o.moneyline_home_odds, o.moneyline_away_odds
FROM sportsbook_game_odds o
JOIN games g ON g.id = o.game_id
WHERE g.status <> 'final'
  AND g.start_time BETWEEN %(now)s AND %(until)s
  AND o.captured_at <= %(now)s
  AND o.captured_at > %(now)s - interval '2 hours'
  AND o.moneyline_home_odds IS NOT NULL
  AND o.moneyline_away_odds IS NOT NULL
ORDER BY o.game_id, o.vendor, o.captured_at DESC
"""

# Polymarket: outcome carries the team, either full name or nickname.
_PM_VWAP = """
SELECT t.game_id,
       sum(CASE WHEN t.outcome IN (h.name, split_part(h.name,' ',
             array_length(string_to_array(h.name,' '),1))) THEN t.price
                ELSE 1 - t.price END * t.size) / nullif(sum(t.size), 0) AS fair_home,
       sum(t.size) AS volume, count(*) AS trades
FROM polymarket_trades t
JOIN games g ON g.id = t.game_id
JOIN teams h ON h.id = g.home_team_id
JOIN teams a ON a.id = g.away_team_id
WHERE t.game_id = ANY(%(games)s)
  AND t.traded_at <= %(now)s AND t.traded_at > %(since)s
  AND t.price BETWEEN 0.02 AND 0.98
  AND (t.outcome IN (h.name, split_part(h.name,' ',
        array_length(string_to_array(h.name,' '),1)))
    OR t.outcome IN (a.name, split_part(a.name,' ',
        array_length(string_to_array(a.name,' '),1))))
GROUP BY t.game_id
"""

# Kalshi: the ticker suffix is the team abbreviation. Four of them differ
# from ours (CONN/GSV/LVA/NYL), so they are aliased inline rather than
# silently dropped -- an unmapped suffix would look like a quiet market.
_KX_VWAP = """
WITH ali(k, t) AS (VALUES ('CONN','CON'),('GSV','GS'),('LVA','LV'),('NYL','NY')),
tagged AS (
  SELECT k.game_id, k.size, k.yes_price,
         COALESCE(a.t, split_part(k.market_ticker,'-',3)) AS tm
  FROM kalshi_trades k
  LEFT JOIN ali a ON a.k = split_part(k.market_ticker,'-',3)
  WHERE k.game_id = ANY(%(games)s)
    AND k.traded_at <= %(now)s AND k.traded_at > %(since)s
    AND k.yes_price BETWEEN 0.02 AND 0.98)
SELECT t.game_id,
       sum(CASE WHEN t.tm = h.abbreviation THEN t.yes_price
                WHEN t.tm = a.abbreviation THEN 1 - t.yes_price END * t.size)
         / nullif(sum(t.size), 0) AS fair_home,
       sum(t.size) AS volume, count(*) AS trades
FROM tagged t
JOIN games g ON g.id = t.game_id
JOIN teams h ON h.id = g.home_team_id
JOIN teams a ON a.id = g.away_team_id
WHERE t.tm IN (h.abbreviation, a.abbreviation)
GROUP BY t.game_id
"""


@dataclass(frozen=True, slots=True)
class DivergenceLogResult:
    games_watched: int = 0
    venues_priced: int = 0
    divergences_found: int = 0
    rows_inserted: int = 0


@dataclass(frozen=True, slots=True)
class GradeResult:
    considered: int = 0
    written: int = 0
    survived: int = 0


def log_divergences(
    db: Database,
    *,
    window: timedelta = DEFAULT_WINDOW,
    lookback: timedelta = DEFAULT_LOOKBACK,
    min_volume: float = DEFAULT_MIN_VOLUME,
    now: datetime | None = None,
) -> DivergenceLogResult:
    """Detect divergences against current prices and append them."""
    at = now or datetime.now(UTC)
    params = {"now": at, "until": at + window}
    with db.connection() as conn:
        rows = conn.execute(_LATEST_QUOTES, params).fetchall()
        if not rows:
            return DivergenceLogResult()

        quotes: dict[int, list[BookQuote]] = defaultdict(list)
        for game_id, vendor, home, away in rows:
            quotes[game_id].append(
                BookQuote(vendor=vendor, home_odds=int(home), away_odds=int(away))
            )

        vparams = {"games": list(quotes), "now": at, "since": at - lookback}
        prices: list[VenuePrice] = []
        observations: list[DivergenceObservation] = []
        for venue, sql in (("polymarket", _PM_VWAP), ("kalshi", _KX_VWAP)):
            for game_id, fair_home, volume, trades in conn.execute(sql, vparams):
                if fair_home is None:
                    continue
                price = VenuePrice(
                    venue=venue,
                    fair_home=float(fair_home),
                    volume=float(volume),
                    trade_count=int(trades),
                )
                prices.append(price)
                for d in detect_divergences(
                    quotes[game_id], price, min_volume=min_volume
                ):
                    observations.append(
                        DivergenceObservation(
                            game_id=game_id,
                            observed_at=at,
                            venue=venue,
                            side=d.side,
                            book_vendor=d.book_vendor,
                            book_odds=d.book_odds,
                            book_implied=d.book_implied,
                            venue_fair=d.venue_fair,
                            venue_volume=price.volume,
                            venue_trade_count=price.trade_count,
                            edge=d.edge,
                        )
                    )
        inserted = divergence_repo.record_divergences(conn, observations)
        conn.commit()

    logger.info(
        "divergence log: %d game(s), %d venue price(s), %d divergence(s), %d new",
        len(quotes), len(prices), len(observations), inserted,
    )
    return DivergenceLogResult(
        games_watched=len(quotes),
        venues_priced=len(prices),
        divergences_found=len(observations),
        rows_inserted=inserted,
    )


def recheck_prices(db: Database) -> GradeResult:
    """Was the price still there at the next quote from that book?

    THE executability question. `survived` means the same book's next
    observed price for that side was at least as good, so a bettor arriving
    one capture later could still have taken it.

    Takes no clock: it is anchored to each observation's own `observed_at`,
    not to now, so a re-run months later grades the same rows identically.
    """
    considered = written = survived = 0
    with db.connection() as conn:
        for obs_id, game_id, observed_at, side, book_odds in (
            divergence_repo.pending_recheck(conn)
        ):
            col = "moneyline_home_odds" if side == "home" else "moneyline_away_odds"
            nxt = conn.execute(
                f"SELECT captured_at, {col} FROM sportsbook_game_odds "
                "WHERE game_id = %s AND captured_at > %s AND "
                f"{col} IS NOT NULL ORDER BY captured_at LIMIT 1",
                (game_id, observed_at),
            ).fetchone()
            considered += 1
            if nxt is None:
                continue
            recheck_at, recheck_odds = nxt[0], int(nxt[1])
            still = american_to_implied(recheck_odds) <= american_to_implied(book_odds)
            written += divergence_repo.write_recheck(
                conn,
                obs_id,
                recheck_at=recheck_at,
                recheck_odds=recheck_odds,
                survived=still,
            )
            survived += int(still)
        conn.commit()
    logger.info(
        "divergence recheck: %d considered, %d written, %d survived",
        considered, written, survived,
    )
    return GradeResult(considered=considered, written=written, survived=survived)


def grade_closings(db: Database) -> GradeResult:
    """Closing price and outcome for finished games.

    CLV is `closing_implied - book_implied`: positive means the price taken
    was cheaper than the close. This is the metric to judge the log by --
    it reaches t=3 in ~120 observations, where ROI needs ~10,600.
    """
    considered = written = 0
    with db.connection() as conn:
        for obs_id, game_id, side, book_implied in (
            divergence_repo.pending_close_grade(conn)
        ):
            col = "moneyline_home_odds" if side == "home" else "moneyline_away_odds"
            row = conn.execute(
                f"SELECT max({col}) FROM sportsbook_game_odds o "
                "JOIN games g ON g.id = o.game_id "
                "WHERE o.game_id = %s AND o.captured_at < g.start_time "
                f"AND {col} IS NOT NULL "
                "AND o.captured_at = (SELECT max(captured_at) FROM sportsbook_game_odds x "
                "  JOIN games g2 ON g2.id = x.game_id WHERE x.game_id = o.game_id "
                f"  AND x.captured_at < g2.start_time AND x.{col} IS NOT NULL)",
                (game_id,),
            ).fetchone()
            considered += 1
            if row is None or row[0] is None:
                continue
            closing_odds = int(row[0])
            scores = conn.execute(
                "SELECT home_score > away_score FROM games WHERE id = %s", (game_id,)
            ).fetchone()
            if scores is None or scores[0] is None:
                continue
            won = bool(scores[0]) if side == "home" else not bool(scores[0])
            closing_implied = american_to_implied(closing_odds)
            written += divergence_repo.write_close_grade(
                conn,
                obs_id,
                closing_odds=closing_odds,
                closing_implied=closing_implied,
                clv=closing_implied - float(book_implied),
                won=won,
            )
        conn.commit()
    logger.info("divergence close grade: %d considered, %d written", considered, written)
    return GradeResult(considered=considered, written=written)
