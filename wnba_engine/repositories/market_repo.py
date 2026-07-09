"""Prediction-market snapshot persistence. Append-only — never updated."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import Connection

from wnba_engine.models.markets import MarketSnapshot

_INSERT_SNAPSHOT = """
INSERT INTO market_price_snapshots (
    provider, market_external_id, event_external_id, game_id, player_id,
    title, outcome,
    yes_bid, yes_ask, last_price, implied_probability,
    volume, liquidity, open_interest,
    status, close_time, captured_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def insert_snapshots(
    conn: Connection,
    snapshots: Sequence[MarketSnapshot],
    *,
    game_id_by_market: Mapping[str, int] | None = None,
    player_id_by_market: Mapping[str, int] | None = None,
) -> int:
    """Append snapshot rows; returns the number inserted.

    game_id_by_market optionally maps market_external_id -> canonical game
    id for markets that resolve to a single game (per-game winner markets,
    player-prop markets where the player's game could be pinned down).
    player_id_by_market optionally maps market_external_id -> canonical
    player id for player-prop markets (independent of game_id -- a prop
    can resolve to a player without resolving to a specific game, e.g. a
    far-future prop beyond the synced schedule). Futures/award markets
    simply stay unmapped (NULL game_id and player_id).
    """
    game_ids = game_id_by_market or {}
    player_ids = player_id_by_market or {}
    with conn.cursor() as cursor:
        cursor.executemany(
            _INSERT_SNAPSHOT,
            [
                (
                    snap.provider,
                    snap.market_external_id,
                    snap.event_external_id,
                    game_ids.get(snap.market_external_id),
                    player_ids.get(snap.market_external_id),
                    snap.title,
                    snap.outcome,
                    snap.yes_bid,
                    snap.yes_ask,
                    snap.last_price,
                    snap.implied_probability,
                    snap.volume,
                    snap.liquidity,
                    snap.open_interest,
                    snap.status,
                    snap.close_time,
                    snap.captured_at,
                )
                for snap in snapshots
            ],
        )
    return len(snapshots)
