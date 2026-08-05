"""Backfill every on-chain Polymarket fill for WNBA markets.

This is the recovery path AGENTS.md said did not exist. Gamma enumerates the
markets (including `closed=true`, which the live snapshot ingest skips by
default), and data-api returns each one's complete fill history -- verified
back to 2024-09-20 for WNBA, with no rolling-window limit.

Two things make this cheap enough to re-run: the pipeline resolves a game id
ONCE per market rather than per fill, and `known_condition_ids` lets a resumed
run skip markets already stored. Neither is required for correctness; the
UNIQUE constraint is.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.models.market_history import PolymarketTrade
from wnba_engine.polymarket.client import PolymarketClient
from wnba_engine.polymarket.data_client import TRADES_PAGE_LIMIT, PolymarketDataClient
from wnba_engine.polymarket.game_matching import parse_matchup_teams
from wnba_engine.polymarket.trade_parser import parse_trades
from wnba_engine.repositories import entity_repo, market_history_repo

logger = logging.getLogger(__name__)

#: Same window the snapshot pipeline uses: a Polymarket close_time is a
#: resolution deadline, not a tip-off.
GAME_DATE_MATCH_WINDOW = timedelta(days=3)
#: Offset pages per market. 500 fills/page, so this allows 100k fills in one
#: market -- far beyond any observed WNBA market (the busiest sampled had
#: ~700) and low enough that a pagination bug terminates instead of looping.
MAX_PAGES_PER_MARKET = 200
#: Gamma event pages to walk per closed/open pass.
MAX_EVENT_PAGES = 20


@dataclass(frozen=True, slots=True)
class MarketRef:
    """One Polymarket market worth backfilling."""

    condition_id: str
    title: str
    close_time: datetime | None


@dataclass(frozen=True, slots=True)
class TradeBackfillResult:
    markets_seen: int = 0
    markets_fetched: int = 0
    markets_skipped: int = 0
    trades_inserted: int = 0
    games_matched: int = 0


def backfill_polymarket_trades(
    db: Database,
    gamma: PolymarketClient,
    data: PolymarketDataClient,
    *,
    resume: bool = True,
    captured_at: datetime | None = None,
    market_limit: int | None = None,
) -> TradeBackfillResult:
    """Walk every WNBA market and store its complete fill history.

    `resume=True` skips markets that already have fills stored. Pass False
    after a parser change, or to pick up new fills on markets that are still
    open -- a market seen yesterday will have traded since, and skipping it
    on the basis of "we have some of its trades" would freeze it.
    """
    stamped = captured_at or datetime.now(UTC)
    # Deduplicated by condition id: Gamma paginates by EVENT, an event can
    # carry the same market in more than one page near a page boundary, and
    # the closed/open passes can both return a market that resolved between
    # them. Duplicates would not corrupt anything -- the UNIQUE constraint
    # sees to that -- but each one costs a full re-walk of that market's
    # pages, which is the expensive part of this backfill.
    refs: list[MarketRef] = []
    seen_ids: set[str] = set()
    for ref in _discover_markets(gamma):
        if ref.condition_id in seen_ids:
            continue
        seen_ids.add(ref.condition_id)
        refs.append(ref)
    if market_limit is not None:
        refs = refs[:market_limit]

    with db.connection() as conn:
        already = market_history_repo.known_condition_ids(conn) if resume else frozenset()

    seen = fetched = skipped = inserted = matched = 0
    for ref in refs:
        seen += 1
        if ref.condition_id in already:
            skipped += 1
            continue
        trades = _fetch_all_trades(data, ref.condition_id, stamped)
        fetched += 1
        if not trades:
            continue
        with db.connection() as conn:
            game_id = _resolve_game_id(conn, ref)
            if game_id is not None:
                matched += 1
            inserted += market_history_repo.insert_trades(
                conn,
                trades,
                game_id_by_condition={ref.condition_id: game_id} if game_id else {},
            )
            conn.commit()
        logger.debug(
            "polymarket trades %s: %d fill(s), game_id=%s", ref.title, len(trades), game_id
        )

    logger.info(
        "polymarket trade backfill: %d market(s) seen, %d fetched, %d skipped, "
        "%d trade(s) inserted, %d market(s) matched to a game",
        seen, fetched, skipped, inserted, matched,
    )
    return TradeBackfillResult(seen, fetched, skipped, inserted, matched)


def _discover_markets(gamma: PolymarketClient) -> Iterator[MarketRef]:
    """Every WNBA market Gamma will list, closed ones included.

    BOTH passes are required and the closed one carries almost everything:
    the live ingest only ever asks for `closed=false`, so a game that has
    already resolved is invisible to it. That is fine for a price snapshot
    and useless for a history backfill.
    """
    for closed in (True, False):
        for offset in range(0, MAX_EVENT_PAGES * 100, 100):
            payload = gamma.fetch_wnba_events_page(closed=closed, limit=100, offset=offset)
            if not isinstance(payload, Sequence) or not payload:
                break
            for event in payload:
                if not isinstance(event, dict):
                    continue
                for market in event.get("markets") or []:
                    ref = _market_ref(market)
                    if ref is not None:
                        yield ref
            if len(payload) < 100:
                break


def _market_ref(market: object) -> MarketRef | None:
    if not isinstance(market, dict):
        return None
    condition_id = market.get("conditionId")
    question = market.get("question")
    if not isinstance(condition_id, str) or not condition_id:
        return None
    if not isinstance(question, str) or not question:
        return None
    return MarketRef(condition_id, question, _close_time(market))


def _close_time(market: dict[str, object]) -> datetime | None:
    """Prefer `gameStartTime` over `endDateIso`.

    `endDateIso` is a bare DATE for game markets ("2026-08-03") while
    `gameStartTime` carries the real tip-off ("2026-08-03 23:30:00+00").
    Anchoring a team/date lookup on midnight rather than tip-off is usually
    harmless given a 3-day window, but it is wrong for free and it is the
    same field `market_price_snapshots.close_time` currently gets wrong.
    """
    for key in ("gameStartTime", "endDateIso"):
        raw = market.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        text = raw.replace("Z", "+00:00").replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _fetch_all_trades(
    data: PolymarketDataClient, condition_id: str, captured_at: datetime
) -> tuple[PolymarketTrade, ...]:
    """Page through one market's fills until the API runs out."""
    collected: list[PolymarketTrade] = []
    for page in range(MAX_PAGES_PER_MARKET):
        payload = data.fetch_trades_page(
            condition_id, limit=TRADES_PAGE_LIMIT, offset=page * TRADES_PAGE_LIMIT
        )
        batch = parse_trades(payload, captured_at=captured_at, context=f"trades[{condition_id}]")
        collected.extend(batch)
        if len(batch) < TRADES_PAGE_LIMIT:
            return tuple(collected)
    logger.warning(
        "polymarket market %s hit the %d-page ceiling; history may be truncated",
        condition_id, MAX_PAGES_PER_MARKET,
    )
    return tuple(collected)


def _resolve_game_id(conn: Connection, ref: MarketRef) -> int | None:
    """Canonical game id for a matchup market, or None.

    Only two-team matchup titles resolve. Spread/total/prop markets carry the
    same conditionId shape but a title this matcher deliberately rejects, and
    futures resolve to no game at all -- all three correctly stay NULL rather
    than being forced onto a nearby game.
    """
    if ref.close_time is None:
        return None
    parsed = parse_matchup_teams(ref.title)
    if parsed is None:
        return None
    team_a, team_b = parsed
    return entity_repo.find_game_id_by_teams(
        conn, team_a, team_b, ref.close_time, window=GAME_DATE_MATCH_WINDOW
    )
