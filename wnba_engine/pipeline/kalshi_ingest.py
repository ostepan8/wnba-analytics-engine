"""Kalshi ingestion: WNBA series -> market price snapshots (append-only).

KXWNBAGAME markets (event tickers like KXWNBAGAME-26JUL09INDPHX) get their
game_id resolved at ingest time via kalshi.game_matching + a team/date
lookup against the canonical games table. Per-game player-prop markets
(KXWNBAPTS/REB/AST/3PT, ...) get their player_id resolved via
kalshi.player_prop_matching + a name lookup, and their game_id resolved
from there via the player's own recent team (props carry no team name or
decodable team code -- see player_prop_matching's docstring). Team-level
per-game derivative markets (spreads, totals, quarter/half winners,
overtime) get their game_id resolved via kalshi.team_market_matching.
Season-long futures/award markets stay unmapped -- there's no single game
to resolve to.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.errors import WnbaEngineError
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.kalshi.game_matching import parse_matchup
from wnba_engine.kalshi.parser import (
    filter_wnba_series,
    parse_markets_page,
    parse_series_list,
)
from wnba_engine.kalshi.player_prop_matching import parse_player_prop
from wnba_engine.kalshi.team_market_matching import (
    parse_single_team_market,
    parse_two_team_market,
)
from wnba_engine.models.markets import MarketSnapshot
from wnba_engine.repositories import entity_repo, market_repo

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SERIES = 50  # safety valve against a runaway cursor loop

# KXWNBAGAME markets settle well after the game (per observed close_time),
# so we anchor matching on the ticker's own date, not close_time. A 1-day
# window absorbs timezone/date-boundary slop around a game's actual start.
GAME_DATE_MATCH_WINDOW = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class KalshiIngestResult:
    series_processed: int = 0
    snapshots_inserted: int = 0
    failures: int = 0


def ingest_kalshi_wnba_markets(
    db: Database,
    client: KalshiClient,
    *,
    series_tickers: Sequence[str] | None = None,
    status: str = "open",
) -> KalshiIngestResult:
    """Snapshot current prices for every WNBA market.

    series_tickers overrides discovery (useful to snapshot just
    KXWNBAGAME); by default all WNBA series are discovered from /series.
    """
    if series_tickers is None:
        series = parse_series_list(client.fetch_sports_series())
        tickers = tuple(s.ticker for s in filter_wnba_series(series))
    else:
        tickers = tuple(series_tickers)

    captured_at = datetime.now(UTC)
    result = KalshiIngestResult()
    for ticker in tickers:
        try:
            inserted = _ingest_series(db, client, ticker, status=status, captured_at=captured_at)
        except WnbaEngineError:
            logger.exception("failed to ingest kalshi series ticker=%s", ticker)
            result = replace(result, failures=result.failures + 1)
            continue
        result = replace(
            result,
            series_processed=result.series_processed + 1,
            snapshots_inserted=result.snapshots_inserted + inserted,
        )
    return result


def _ingest_series(
    db: Database,
    client: KalshiClient,
    series_ticker: str,
    *,
    status: str,
    captured_at: datetime,
) -> int:
    inserted = 0
    cursor: str | None = None
    for _ in range(MAX_PAGES_PER_SERIES):
        payload = client.fetch_markets_page(series_ticker, status=status, cursor=cursor)
        snapshots, cursor = parse_markets_page(payload, captured_at=captured_at)
        if snapshots:
            with db.connection() as conn:
                game_id_by_market = _resolve_game_ids(conn, snapshots)
                player_id_by_market, prop_game_id_by_market = _resolve_player_prop_ids(
                    conn, snapshots
                )
                already_resolved = {**game_id_by_market, **prop_game_id_by_market}
                team_market_game_id_by_market = _resolve_team_market_ids(
                    conn, snapshots, already_resolved
                )
                inserted += market_repo.insert_snapshots(
                    conn,
                    snapshots,
                    game_id_by_market={**already_resolved, **team_market_game_id_by_market},
                    player_id_by_market=player_id_by_market,
                )
                conn.commit()
        if not cursor or not snapshots:
            return inserted
    logger.warning(
        "kalshi pagination exceeded %d pages for series=%s; stopping early",
        MAX_PAGES_PER_SERIES,
        series_ticker,
    )
    return inserted


def _resolve_game_ids(conn: Connection, snapshots: Sequence[MarketSnapshot]) -> dict[str, int]:
    """Map market_external_id -> canonical game id for KXWNBAGAME markets.

    Grouped by event_external_id first: a game's two outcome markets share
    one event ticker/title, so this is one parse + one lookup per game, not
    one per market row.
    """
    game_id_by_market: dict[str, int] = {}
    game_id_by_event: dict[str, int | None] = {}
    for snap in snapshots:
        if snap.event_external_id is None:
            continue
        if snap.event_external_id not in game_id_by_event:
            parsed = parse_matchup(snap.event_external_id, snap.title)
            if parsed is None:
                game_id_by_event[snap.event_external_id] = None
            else:
                game_date, team_a, team_b = parsed
                near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
                game_id_by_event[snap.event_external_id] = entity_repo.find_game_id_by_teams(
                    conn, team_a, team_b, near, window=GAME_DATE_MATCH_WINDOW
                )
        game_id = game_id_by_event[snap.event_external_id]
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return game_id_by_market


def _resolve_player_prop_ids(
    conn: Connection, snapshots: Sequence[MarketSnapshot]
) -> tuple[dict[str, int], dict[str, int]]:
    """Map market_external_id -> player_id, and separately -> game_id, for
    per-game player-prop markets (KXWNBAPTS/REB/AST/3PT, ...).

    Grouped by event_external_id first, same rationale as
    _resolve_game_ids. game_id is best-effort on top of player_id: a prop
    can resolve to a player without resolving to a game (e.g. a far-future
    prop beyond the synced schedule, or a player with no box-score rows
    yet to infer a team from).
    """
    player_id_by_market: dict[str, int] = {}
    game_id_by_market: dict[str, int] = {}
    resolved_by_event: dict[str, tuple[int, int | None] | None] = {}
    for snap in snapshots:
        if snap.event_external_id is None:
            continue
        if snap.event_external_id not in resolved_by_event:
            resolved_by_event[snap.event_external_id] = _resolve_one_player_prop(
                conn, snap.event_external_id, snap.title
            )
        resolved = resolved_by_event[snap.event_external_id]
        if resolved is None:
            continue
        player_id, game_id = resolved
        player_id_by_market[snap.market_external_id] = player_id
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return player_id_by_market, game_id_by_market


def _resolve_one_player_prop(
    conn: Connection, event_external_id: str, title: str
) -> tuple[int, int | None] | None:
    parsed = parse_player_prop(event_external_id, title)
    if parsed is None:
        return None
    game_date, player_name = parsed
    player_id = entity_repo.find_player_by_name(conn, player_name)
    if player_id is None:
        return None
    team_id = entity_repo.find_recent_team_id_for_player(conn, player_id)
    if team_id is None:
        return player_id, None
    near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
    game_id = entity_repo.find_game_id_by_team_and_date(
        conn, team_id, near, window=GAME_DATE_MATCH_WINDOW
    )
    return player_id, game_id


def _resolve_team_market_ids(
    conn: Connection,
    snapshots: Sequence[MarketSnapshot],
    already_resolved: dict[str, int],
) -> dict[str, int]:
    """Map market_external_id -> canonical game id for team-level
    per-game derivative markets (spreads, totals, quarter/half winners,
    overtime).

    Resolved per-market rather than per-event: unlike KXWNBAGAME, a
    derivative event's markets can carry different titles for the same
    event ticker (e.g. KXWNBASPREAD's two outcome markets each name a
    different team). already_resolved marks markets game_matching /
    player_prop_matching already mapped, so they're not reprocessed here
    (also sidesteps KXWNBAGAME's own "X vs Y winner?" title superficially
    matching the two-team regex below).
    """
    game_id_by_market: dict[str, int] = {}
    for snap in snapshots:
        if snap.event_external_id is None or snap.market_external_id in already_resolved:
            continue
        game_id = _resolve_one_team_market(conn, snap.event_external_id, snap.title)
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return game_id_by_market


def _resolve_one_team_market(conn: Connection, event_external_id: str, title: str) -> int | None:
    two_team = parse_two_team_market(event_external_id, title)
    if two_team is not None:
        game_date, team_a, team_b = two_team
        near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
        return entity_repo.find_game_id_by_teams(
            conn, team_a, team_b, near, window=GAME_DATE_MATCH_WINDOW
        )
    single_team = parse_single_team_market(event_external_id, title)
    if single_team is not None:
        game_date, team_name = single_team
        team_id = entity_repo.find_team_by_name_fragment(conn, team_name)
        if team_id is None:
            return None
        near = datetime.combine(game_date, time(12, 0), tzinfo=UTC)
        return entity_repo.find_game_id_by_team_and_date(
            conn, team_id, near, window=GAME_DATE_MATCH_WINDOW
        )
    return None
