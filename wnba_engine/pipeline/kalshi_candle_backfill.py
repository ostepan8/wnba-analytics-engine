"""Backfill Kalshi OHLC bars for WNBA game markets.

The counterpart to `polymarket_trade_backfill`, and the second half of the
correction to AGENTS.md's "no historical endpoint" claim. Kalshi's
candlesticks route returns bars back to market creation, so a market that
settled in May is still fully readable in August.

Coverage note worth knowing before reading the numbers: Kalshi's per-GAME
markets only open near tip-off, so a settled game market yields a handful of
hourly bars rather than a week of them. That is the product, not a gap -- the
long series live on season-scale markets (futures, win totals).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.kalshi.candle_parser import parse_candlesticks
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.kalshi.game_matching import parse_matchup
from wnba_engine.models.market_history import KalshiCandle
from wnba_engine.pipeline.kalshi_ingest import resolve_team_market_game_id
from wnba_engine.repositories import entity_repo, market_history_repo

logger = logging.getLogger(__name__)

#: The game-level series. Moneyline, spread and total -- the three that map
#: onto a canonical game and onto the sportsbook tables we already hold, so
#: the two price sources become directly comparable.
GAME_SERIES: tuple[str, ...] = ("KXWNBAGAME", "KXWNBASPREAD", "KXWNBATOTAL")

#: Period-level derivatives: quarter and half totals and winners. Thinner
#: markets than the full-game ones, and gradeable exactly -- FEATURE_ROADMAP
#: ss9's play aggregation gives per-period scoring, so a quarter total can
#: be settled from our own data rather than taken on trust.
#:
#: Not in GAME_SERIES because they are a separate, larger sweep (7,259
#: settled markets) and because they exist only from 2026-05-26 -- one
#: partial season, with no out-of-sample year. That is the same limitation
#: that turned out to explain the Kalshi moneyline result, so anything
#: measured here inherits the caveat.
DERIVATIVE_SERIES: tuple[str, ...] = (
    "KXWNBA1QTOTAL", "KXWNBA2QTOTAL", "KXWNBA3QTOTAL", "KXWNBA4QTOTAL",
    "KXWNBA1HTOTAL", "KXWNBA2HTOTAL",
    "KXWNBA1QWINNER", "KXWNBA2QWINNER", "KXWNBA3QWINNER", "KXWNBA4QWINNER",
    "KXWNBA1HWINNER", "KXWNBA2HWINNER",
)

#: Ticker-encoded dates are exact, so a tight window (matches kalshi_ingest).
GAME_DATE_MATCH_WINDOW = timedelta(days=1)

#: Request window caps, measured against the live API on 2026-08-03: hourly
#: bars accept ~180 days and reject 400 with a bare HTTP 400; 1-minute bars
#: accept ~3 days and reject 7. Chunking to these keeps a wide backfill from
#: looking like a broken endpoint.
MAX_WINDOW_DAYS: dict[int, int] = {1: 3, 60: 150, 1440: 150}
DEFAULT_WINDOW_DAYS = 3

MAX_MARKET_PAGES = 40


@dataclass(frozen=True, slots=True)
class CandleBackfillResult:
    series_processed: int = 0
    markets_seen: int = 0
    markets_fetched: int = 0
    candles_inserted: int = 0
    games_matched: int = 0


def backfill_kalshi_candles(
    db: Database,
    client: KalshiClient,
    *,
    series: Sequence[str] = GAME_SERIES,
    period_minutes: int = 60,
    since: datetime | None = None,
    captured_at: datetime | None = None,
    market_limit: int | None = None,
) -> CandleBackfillResult:
    """Store OHLC bars for every market in `series`.

    `since` defaults to 2022-01-01, which is earlier than any WNBA market
    Kalshi lists (settled game markets start 2026-05-25) and therefore means
    "everything" without hard-coding a season boundary that would silently
    truncate once 2027 opens.
    """
    stamped = captured_at or datetime.now(UTC)
    start = since or datetime(2022, 1, 1, tzinfo=UTC)
    processed = seen = fetched = inserted = matched = 0

    for series_ticker in series:
        processed += 1
        tickers = list(_discover_markets(client, series_ticker, stamped))
        if market_limit is not None:
            tickers = tickers[:market_limit]
        for market_ticker, title, event_ticker, close_time in tickers:
            seen += 1
            # Bound the request window to this market's own lifetime. A
            # market that closed in May has no bars in August, and asking
            # anyway is the difference between ~4k and ~47k requests.
            window_start = start
            window_end = stamped
            if close_time is not None:
                window_start = max(start, close_time - MARKET_LOOKBACK)
                window_end = min(stamped, close_time + timedelta(days=1))
            candles = _fetch_candles(
                client, series_ticker, market_ticker, window_start,
                window_end, period_minutes, title,
            )
            if not candles:
                continue
            fetched += 1
            with db.connection() as conn:
                game_id = _resolve_game_id(conn, event_ticker, title)
                if game_id is not None:
                    matched += 1
                inserted += market_history_repo.insert_candles(
                    conn,
                    candles,
                    game_id_by_market={market_ticker: game_id} if game_id else {},
                )
                conn.commit()

    logger.info(
        "kalshi candle backfill: %d series, %d market(s) seen, %d with bars, "
        "%d bar(s) inserted, %d matched to a game",
        processed, seen, fetched, inserted, matched,
    )
    return CandleBackfillResult(processed, seen, fetched, inserted, matched)


#: How far before a market's close to start asking for bars. A Kalshi
#: per-game market opens days, not months, before tip-off; a season-scale
#: market opens at the start of the season. 200 days covers both.
#:
#: This bound is what makes a full sweep affordable. Chunking every market
#: from a fixed 2022 epoch instead costs ~12 windows each, and at ~3,900 WNBA
#: markets that is ~47,000 requests -- over six hours at the client's 0.5s
#: pacing, almost all of it asking about windows in which the market did not
#: exist. Anchored on close_time it is one or two windows per market.
MARKET_LOOKBACK = timedelta(days=200)


def _discover_markets(
    client: KalshiClient, series_ticker: str, captured_at: datetime
) -> Iterator[tuple[str, str, str | None, datetime | None]]:
    """(market ticker, title, event ticker, close time) per market in a series.

    `close_time` is carried out of discovery purely so the caller can bound
    its candlestick window to the market's lifetime -- see MARKET_LOOKBACK
    for why that one field decides whether a full sweep takes 20 minutes or
    six hours.

    BOTH settled and open statuses are walked. `kalshi_ingest` asks only for
    open markets because it snapshots live prices; a history backfill that
    did the same would miss every game already played, which is the entire
    point of the exercise.
    """
    for status in ("settled", "open"):
        cursor: str | None = None
        for _ in range(MAX_MARKET_PAGES):
            payload = client.fetch_markets_page(
                series_ticker, status=status, cursor=cursor, limit=1000
            )
            snapshots, cursor = _parse_markets(payload, captured_at)
            for snap in snapshots:
                yield (
                    snap.market_external_id,
                    snap.title,
                    snap.event_external_id,
                    snap.close_time,
                )
            if not cursor or not snapshots:
                break


def _parse_markets(payload: object, captured_at: datetime):
    from wnba_engine.kalshi.parser import parse_markets_page

    return parse_markets_page(payload, captured_at=captured_at)


def _fetch_candles(
    client: KalshiClient,
    series_ticker: str,
    market_ticker: str,
    start: datetime,
    end: datetime,
    period_minutes: int,
    title: str | None = None,
) -> tuple[KalshiCandle, ...]:
    """Fetch one market's bars, chunked to the API's window cap."""
    span = timedelta(days=MAX_WINDOW_DAYS.get(period_minutes, DEFAULT_WINDOW_DAYS))
    collected: list[KalshiCandle] = []
    window_start = start
    while window_start < end:
        window_end = min(window_start + span, end)
        try:
            payload = client.fetch_candlesticks(
                series_ticker,
                market_ticker,
                start_ts=int(window_start.timestamp()),
                end_ts=int(window_end.timestamp()),
                period_interval=period_minutes,
            )
        except Exception:
            # A market that did not exist during this window 404s, and a
            # series/ticker mismatch 400s. Both are routine across a
            # multi-year sweep of thousands of markets and neither should
            # abort the run -- but they are logged, because a systematic
            # failure would otherwise look like a market that never traded.
            logger.debug(
                "kalshi candles unavailable: %s %s..%s", market_ticker, window_start, window_end
            )
            window_start = window_end
            continue
        collected.extend(
            parse_candlesticks(
                payload,
                series_ticker=series_ticker,
                market_ticker=market_ticker,
                period_minutes=period_minutes,
                captured_at=end,
                title=title,
                context=f"candlesticks[{market_ticker}]",
            )
        )
        window_start = window_end
    return tuple(collected)


def _resolve_game_id(conn: Connection, event_ticker: str | None, title: str) -> int | None:
    """Canonical game id from the ticker-encoded date plus the title teams.

    TWO matchers, tried in order. `parse_matchup` only understands
    KXWNBAGAME's own title shape, so an earlier version of this function
    left every KXWNBASPREAD and KXWNBATOTAL bar unlinked -- 116,000 of the
    135,000 bars in the first full sweep, i.e. most of the table. Spreads
    and totals are exactly the markets worth comparing against
    `sportsbook_game_odds`, so losing them defeated the point.

    `parse_matchup` first because it is the stricter, ticker-anchored one;
    a KXWNBAGAME title also satisfies the looser two-team pattern.
    """
    if not event_ticker:
        return None
    parsed = parse_matchup(event_ticker, title)
    if parsed is not None:
        game_date, team_a, team_b = parsed
        near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
        return entity_repo.find_game_id_by_teams(
            conn, team_a, team_b, near, window=GAME_DATE_MATCH_WINDOW
        )
    # Spreads and totals. Shared with kalshi_ingest rather than
    # re-implemented -- a private second copy here is exactly how every
    # KXWNBASPREAD bar came to be written with a NULL game_id.
    return resolve_team_market_game_id(conn, event_ticker, title)
