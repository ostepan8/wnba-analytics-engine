"""Polymarket ingestion: WNBA-tagged events -> market price snapshots.

Team-matchup markets ("Atlanta Dream vs. Toronto Tempo") get their game_id
resolved at ingest time via polymarket.game_matching + a team/date lookup
against the canonical games table, anchored on the market's own close_time
(the best proxy Polymarket exposes for game date on these markets).
Player-prop markets ("A'ja Wilson: Rebounds O/U 7.5") get their player_id
resolved via polymarket.player_prop_matching + a name lookup, and their
game_id resolved from there via the player's own recent team (same
close_time anchor). Team-level derivative markets ("Spread: Atlanta Dream
(-10.5)", "Golden State Valkyries vs. Toronto Tempo: O/U 165.5") get
their game_id resolved via polymarket.team_market_matching. Futures/award
markets stay unmapped.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.models.markets import MarketSnapshot
from wnba_engine.polymarket.client import PolymarketClient
from wnba_engine.polymarket.game_matching import parse_matchup_teams
from wnba_engine.polymarket.parser import parse_events
from wnba_engine.polymarket.player_prop_matching import parse_player_prop_name
from wnba_engine.polymarket.team_market_matching import (
    parse_spread_market_team,
    parse_total_market_teams,
)
from wnba_engine.repositories import entity_repo, market_repo

logger = logging.getLogger(__name__)

MAX_PAGES = 50  # safety valve against a runaway offset loop

# close_time is a market resolution deadline, not necessarily the exact
# game start -- a wider window than Kalshi's ticker-date match.
GAME_DATE_MATCH_WINDOW = timedelta(days=3)


@dataclass(frozen=True, slots=True)
class PolymarketIngestResult:
    events_seen: int = 0
    snapshots_inserted: int = 0


def ingest_polymarket_wnba_markets(
    db: Database, client: PolymarketClient, *, include_closed: bool = False
) -> PolymarketIngestResult:
    """Snapshot current prices for every WNBA-tagged Polymarket market."""
    captured_at = datetime.now(UTC)
    events_seen = 0
    inserted = 0
    for _ in range(MAX_PAGES):
        payload = client.fetch_wnba_events_page(closed=include_closed, offset=events_seen)
        snapshots = parse_events(payload, captured_at=captured_at)
        # Advance by events actually received and stop only on an empty
        # page: Gamma may serve fewer than the requested limit per page.
        page_events = len(payload) if isinstance(payload, list) else 0
        if page_events == 0:
            return PolymarketIngestResult(events_seen=events_seen, snapshots_inserted=inserted)
        events_seen += page_events
        if snapshots:
            with db.connection() as conn:
                game_id_by_market = _resolve_game_ids(conn, snapshots)
                player_id_by_market, prop_game_id_by_market = _resolve_player_prop_ids(
                    conn, snapshots
                )
                team_market_game_id_by_market = _resolve_team_market_ids(conn, snapshots)
                inserted += market_repo.insert_snapshots(
                    conn,
                    snapshots,
                    game_id_by_market={
                        **game_id_by_market,
                        **prop_game_id_by_market,
                        **team_market_game_id_by_market,
                    },
                    player_id_by_market=player_id_by_market,
                )
                conn.commit()
    logger.warning("polymarket pagination exceeded %d pages; stopping early", MAX_PAGES)
    return PolymarketIngestResult(events_seen=events_seen, snapshots_inserted=inserted)


def _resolve_game_ids(conn: Connection, snapshots: Sequence[MarketSnapshot]) -> dict[str, int]:
    """Map market_external_id -> canonical game id for team-matchup markets.

    Unlike Kalshi, a matchup market's title is unique per market_external_id
    here (no shared event ticker/title across outcome rows), so this is one
    parse + one lookup per matchup market.
    """
    game_id_by_market: dict[str, int] = {}
    for snap in snapshots:
        if snap.close_time is None:
            continue
        parsed = parse_matchup_teams(snap.title)
        if parsed is None:
            continue
        team_a, team_b = parsed
        game_id = entity_repo.find_game_id_by_teams(
            conn, team_a, team_b, snap.close_time, window=GAME_DATE_MATCH_WINDOW
        )
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return game_id_by_market


def _resolve_player_prop_ids(
    conn: Connection, snapshots: Sequence[MarketSnapshot]
) -> tuple[dict[str, int], dict[str, int]]:
    """Map market_external_id -> player_id, and separately -> game_id, for
    player-prop markets ("A'ja Wilson: Rebounds O/U 7.5").

    game_id is best-effort on top of player_id, resolved via the player's
    own recent team + close_time proximity -- a prop can resolve to a
    player without resolving to a game (e.g. a far-future prop beyond the
    synced schedule).
    """
    player_id_by_market: dict[str, int] = {}
    game_id_by_market: dict[str, int] = {}
    for snap in snapshots:
        if snap.close_time is None:
            continue
        player_name = parse_player_prop_name(snap.title)
        if player_name is None:
            continue
        player_id = entity_repo.find_player_by_name(conn, player_name)
        if player_id is None:
            continue
        player_id_by_market[snap.market_external_id] = player_id
        team_id = entity_repo.find_recent_team_id_for_player(conn, player_id)
        if team_id is None:
            continue
        game_id = entity_repo.find_game_id_by_team_and_date(
            conn, team_id, snap.close_time, window=GAME_DATE_MATCH_WINDOW
        )
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return player_id_by_market, game_id_by_market


def _resolve_team_market_ids(
    conn: Connection, snapshots: Sequence[MarketSnapshot]
) -> dict[str, int]:
    """Map market_external_id -> canonical game id for team-level
    derivative markets (totals and spreads with a colon in the title,
    which parse_matchup_teams deliberately excludes -- see
    polymarket/team_market_matching.py). Team names here are Polymarket's
    own full canonical names, so find_game_id_by_teams / find_team_by_name
    (exact match) are enough -- no fragment matching needed, unlike
    Kalshi's short city-name titles.
    """
    game_id_by_market: dict[str, int] = {}
    for snap in snapshots:
        if snap.close_time is None:
            continue
        total_teams = parse_total_market_teams(snap.title)
        if total_teams is not None:
            team_a, team_b = total_teams
            game_id = entity_repo.find_game_id_by_teams(
                conn, team_a, team_b, snap.close_time, window=GAME_DATE_MATCH_WINDOW
            )
            if game_id is not None:
                game_id_by_market[snap.market_external_id] = game_id
            continue
        spread_team = parse_spread_market_team(snap.title)
        if spread_team is None:
            continue
        team_id = entity_repo.find_team_by_name(conn, spread_team)
        if team_id is None:
            continue
        game_id = entity_repo.find_game_id_by_team_and_date(
            conn, team_id, snap.close_time, window=GAME_DATE_MATCH_WINDOW
        )
        if game_id is not None:
            game_id_by_market[snap.market_external_id] = game_id
    return game_id_by_market
