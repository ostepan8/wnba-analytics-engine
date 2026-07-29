"""Prediction-market snapshot persistence. Append-only — never updated."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

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
ON CONFLICT (provider, market_external_id, captured_at) DO NOTHING
"""


def latest_captured_at(conn: Connection, provider: str) -> datetime | None:
    """Newest observation already stored for one provider, or None.

    Used as a high-water mark so replaying a capture directory only loads
    files recorded after what's already here. Correctness doesn't depend
    on it -- the UNIQUE constraint makes re-ingestion a no-op either way
    -- it just avoids re-parsing an archive that grows without bound.
    """
    row = conn.execute(
        "SELECT max(captured_at) FROM market_price_snapshots WHERE provider = %s",
        (provider,),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def insert_snapshots(
    conn: Connection,
    snapshots: Sequence[MarketSnapshot],
    *,
    game_id_by_market: Mapping[str, int] | None = None,
    player_id_by_market: Mapping[str, int] | None = None,
) -> int:
    """Append snapshot rows; returns the number ACTUALLY inserted.

    Duplicates are silently skipped via ON CONFLICT DO NOTHING against
    (provider, market_external_id, captured_at) -- see
    db/migrations/0022_market_snapshot_idempotency.sql. That makes
    replaying a captured payload file a no-op rather than a doubling, so
    the count returned is real inserts, not len(snapshots): a re-ingested
    capture correctly reports 0.


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
        # rowcount after executemany is the total actually written, so
        # conflicts (already-ingested observations) are excluded.
        return max(cursor.rowcount, 0)
