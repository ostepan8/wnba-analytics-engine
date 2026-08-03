"""Re-resolve NULL game_id on already-stored prediction-market rows.

Needed because `ON CONFLICT DO NOTHING` -- the convention that makes every
ingest here safely re-runnable -- also means a re-ingest CANNOT repair a row
it already has. When a matcher is fixed, the fix applies only to rows written
afterwards; everything already stored keeps whatever game_id it got at the
time, which for a broken matcher is NULL.

That is not hypothetical. Kalshi rewrote its market titles between 2026-07-13
and 2026-07-27 (see kalshi/game_matching.py), and by the time it was caught
18,042 snapshot rows had been written with no game link -- 4,712 KXWNBAGAME
and 13,330 KXWNBATOTAL. Re-running snapshot-kalshi does not touch them.

This walks rows with a NULL game_id and fills in whatever the CURRENT matchers
resolve. It never overwrites a non-NULL game_id: a previously matched row was
matched by some earlier version of the same code, and silently rewriting that
would make the table's history depend on when it was last relinked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.kalshi.game_matching import parse_matchup
from wnba_engine.pipeline.kalshi_ingest import resolve_team_market_game_id
from wnba_engine.repositories import entity_repo

logger = logging.getLogger(__name__)

KALSHI_WINDOW_DAYS = 1
POLYMARKET_WINDOW_DAYS = 3


@dataclass(frozen=True, slots=True)
class RelinkResult:
    rows_examined: int = 0
    rows_linked: int = 0
    candles_linked: int = 0


def relink_market_snapshots(db: Database, *, dry_run: bool = False) -> RelinkResult:
    """Fill NULL game_id on market_price_snapshots using current matchers."""
    examined = linked = 0
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT provider, market_external_id, event_external_id, title "
            "FROM market_price_snapshots WHERE game_id IS NULL"
        ).fetchall()
        # Resolution is per MARKET, not per row: one market has hundreds of
        # snapshot rows over time and they all resolve to the same game, so
        # doing the lookup per row would issue the same query hundreds of
        # times for an identical answer.
        for provider, market_id, event_id, title in rows:
            examined += 1
            game_id = _resolve(conn, str(provider), event_id, str(title or ""))
            if game_id is None:
                continue
            linked += 1
            if not dry_run:
                conn.execute(
                    "UPDATE market_price_snapshots SET game_id = %s "
                    "WHERE market_external_id = %s AND provider = %s AND game_id IS NULL",
                    (game_id, market_id, provider),
                )
        if not dry_run:
            conn.commit()
    candles = _relink_candles(db, dry_run=dry_run)
    logger.info(
        "relink: %d unlinked market(s) examined, %d resolved, %d candle market(s) linked%s",
        examined, linked, candles, " (dry run, nothing written)" if dry_run else "",
    )
    return RelinkResult(examined, linked, candles)


def _relink_candles(db: Database, *, dry_run: bool) -> int:
    """Same repair for kalshi_candlesticks.

    Needed for the same reason and by the same mechanism: the first full
    sweep resolved only KXWNBAGAME, so spread and total bars -- the ones
    worth comparing against sportsbook_game_odds -- were written with a
    NULL game_id that no re-run can fix.
    """
    linked = 0
    with db.connection() as conn:
        # Title comes from the candle row itself (migration 0026), not from
        # market_price_snapshots. The snapshot ingest only ever sees markets
        # that are currently OPEN, so a settled spread or total -- which is
        # most of this table -- has no snapshot to borrow a title from, and
        # an earlier version of this function repaired 2 markets out of
        # 2,948 for exactly that reason.
        rows = conn.execute(
            "SELECT DISTINCT market_ticker, title FROM kalshi_candlesticks "
            "WHERE game_id IS NULL AND title IS NOT NULL"
        ).fetchall()
        for ticker, title in rows:
            game_id = _resolve_kalshi(conn, str(ticker), str(title))
            if game_id is None:
                continue
            linked += 1
            if not dry_run:
                conn.execute(
                    "UPDATE kalshi_candlesticks SET game_id = %s "
                    "WHERE market_ticker = %s AND game_id IS NULL",
                    (game_id, ticker),
                )
        if not dry_run:
            conn.commit()
    return linked


def _resolve(conn: Connection, provider: str, event_id: object, title: str) -> int | None:
    if provider == "kalshi":
        return _resolve_kalshi(conn, str(event_id or ""), title)
    if provider == "polymarket":
        return _resolve_polymarket(conn, title)
    return None


def _resolve_kalshi(conn: Connection, event_id: str, title: str) -> int | None:
    """KXWNBAGAME first, then the two-team derivative shape.

    Order matters: a KXWNBAGAME title also satisfies the looser two-team
    pattern, and `parse_matchup` is the stricter, ticker-anchored one.
    """
    if not event_id:
        return None
    parsed = parse_matchup(event_id, title)
    if parsed is not None:
        game_date, team_a, team_b = parsed
        near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
        return entity_repo.find_game_id_by_teams(
            conn, team_a, team_b, near, window=timedelta(days=KALSHI_WINDOW_DAYS)
        )
    return resolve_team_market_game_id(conn, event_id, title)


def _resolve_polymarket(conn: Connection, title: str) -> int | None:
    """Polymarket titles carry no date, so this needs the market's own close
    time -- which the caller does not have here. Deliberately unimplemented
    rather than guessed: a team/date lookup with no date would match the
    wrong meeting of two teams that play each other four times a season.
    """
    del conn, title
    return None


