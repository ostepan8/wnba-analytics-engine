"""Backfill Kalshi trade history from the HISTORICAL tier.

Exists because every Kalshi query in this project was hitting the wrong
tier. Kalshi partitions exchange data at a cutoff (`GET /historical/cutoff`,
2026-06-05 as of writing); markets settled before it are served only from
`/historical/*` and are invisible to the endpoints used everywhere else.

The cost of that was a season. `/markets?series_ticker=KXWNBAGAME` returns
364 settled markets from 2026-05-22. `/historical/markets` returns 760 from
**2025-05-23**, including the 2025 Finals. Every Kalshi conclusion in
MODELING_FINDINGS.md -- notably the "follow Kalshi" result that turned out
to be a home-bias artefact -- rested on one partial season, and the
out-of-sample year it needed was behind a path nobody had tried.

Candlesticks 404 for pre-cutoff markets, so trades are the only way to
price them, and they are the better shape anyway: individual timestamped
prints rather than hourly bars, exactly what made `polymarket_trades` more
useful than its quote snapshots.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.kalshi.game_matching import parse_matchup
from wnba_engine.kalshi.parser import PROVIDER
from wnba_engine.kalshi.trade_parser import parse_trades
from wnba_engine.models.market_history import KalshiTrade
from wnba_engine.pipeline.kalshi_ingest import resolve_team_market_game_id
from wnba_engine.repositories import entity_repo, market_history_repo

logger = logging.getLogger(__name__)

GAME_DATE_MATCH_WINDOW = timedelta(days=1)
#: Pages of 1,000 trades per market. Playoff markets reach ~7,700 trades,
#: so eight pages covers the busiest observed with room to spare while
#: still terminating if a cursor ever loops.
MAX_TRADE_PAGES = 40
MAX_MARKET_PAGES = 25


@dataclass(frozen=True, slots=True)
class KalshiTradeBackfillResult:
    markets_seen: int = 0
    markets_fetched: int = 0
    markets_skipped: int = 0
    trades_inserted: int = 0
    games_matched: int = 0


def backfill_kalshi_trades(
    db: Database,
    client: KalshiClient,
    *,
    series: Sequence[str] = ("KXWNBAGAME",),
    resume: bool = True,
    before: datetime | None = None,
    captured_at: datetime | None = None,
    market_limit: int | None = None,
    live: bool = False,
) -> KalshiTradeBackfillResult:
    """Store trades for the named series.

    `before` filters to markets closing before an instant -- pass
    `2026-01-01` to fetch only the 2025 season, which is the out-of-sample
    year the existing Kalshi analysis lacks. Omit it for everything.

    `live=True` switches BOTH the market list and the trade fetch to the
    live tier, which is the only tier that can see a game that has not been
    played yet. The historical tier serves what settled before Kalshi's
    cutoff, so it is exactly the wrong place to look for tonight's game --
    and the divergence log only cares about games that have not happened.
    Implies `resume=False` in practice: an open market trades continuously,
    so skipping it because some of its fills are stored would freeze it.
    """
    stamped = captured_at or datetime.now(UTC)
    with db.connection() as conn:
        already = (
            market_history_repo.known_kalshi_trade_markets(conn)
            if resume
            else frozenset()
        )

    seen = fetched = skipped = inserted = matched = 0
    for series_ticker in series:
        markets = list(_discover(client, series_ticker, before, live=live))
        if market_limit is not None:
            markets = markets[:market_limit]
        for ticker, title, event_ticker in markets:
            seen += 1
            if ticker in already:
                skipped += 1
                continue
            trades = _fetch_trades(client, ticker, series_ticker, stamped, live=live)
            if not trades:
                continue
            fetched += 1
            with db.connection() as conn:
                game_id = _resolve_game_id(conn, event_ticker, title)
                if game_id is not None:
                    matched += 1
                inserted += market_history_repo.insert_kalshi_trades(
                    conn,
                    trades,
                    game_id_by_market={ticker: game_id} if game_id else {},
                )
                conn.commit()

    logger.info(
        "kalshi trade backfill: %d market(s) seen, %d fetched, %d skipped, "
        "%d trade(s) inserted, %d matched to a game",
        seen, fetched, skipped, inserted, matched,
    )
    return KalshiTradeBackfillResult(seen, fetched, skipped, inserted, matched)


def _discover(
    client: KalshiClient, series_ticker: str, before: datetime | None, *, live: bool = False
) -> Iterator[tuple[str, str, str]]:
    """(market ticker, title, event ticker) from the requested tier."""
    cursor: str | None = None
    for _ in range(MAX_MARKET_PAGES):
        payload = (
            client.fetch_open_markets_page(series_ticker, cursor=cursor)
            if live
            else client.fetch_historical_markets_page(series_ticker, cursor=cursor)
        )
        if not isinstance(payload, dict):
            return
        markets = payload.get("markets") or []
        for market in markets:
            if not isinstance(market, dict):
                continue
            ticker = market.get("ticker")
            title = market.get("title")
            event = market.get("event_ticker")
            close = market.get("close_time")
            if not isinstance(ticker, str) or not isinstance(title, str):
                continue
            if before is not None and isinstance(close, str):
                # String compare is safe: both are ISO-8601 UTC.
                if close >= before.isoformat().replace("+00:00", "Z"):
                    continue
            yield ticker, title, event if isinstance(event, str) else ""
        cursor = payload.get("cursor")
        if not cursor or not markets:
            return


def _fetch_trades(
    client: KalshiClient,
    ticker: str,
    series_ticker: str,
    captured_at: datetime,
    *,
    live: bool = False,
) -> tuple[KalshiTrade, ...]:
    collected: list[KalshiTrade] = []
    cursor: str | None = None
    for _ in range(MAX_TRADE_PAGES):
        # Both tiers return the same record shape, so one parser serves
        # both -- verified 2026-08-05 against /markets/trades.
        payload = (
            client.fetch_live_trades_page(ticker, cursor=cursor)
            if live
            else client.fetch_historical_trades_page(ticker, cursor=cursor)
        )
        batch, cursor = parse_trades(
            payload,
            captured_at=captured_at,
            series_ticker=series_ticker,
            context=f"historical/trades[{ticker}]",
        )
        collected.extend(batch)
        if not cursor or not batch:
            return tuple(collected)
    logger.warning(
        "%s market %s hit the %d-page ceiling; history may be truncated",
        PROVIDER, ticker, MAX_TRADE_PAGES,
    )
    return tuple(collected)


def _resolve_game_id(conn: Connection, event_ticker: str, title: str) -> int | None:
    """Same two matchers the candlestick backfill uses, in the same order."""
    if not event_ticker:
        return None
    parsed = parse_matchup(event_ticker, title)
    if parsed is not None:
        game_date, team_a, team_b = parsed
        near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
        return entity_repo.find_game_id_by_teams(
            conn, team_a, team_b, near, window=GAME_DATE_MATCH_WINDOW
        )
    return resolve_team_market_game_id(conn, event_ticker, title)
