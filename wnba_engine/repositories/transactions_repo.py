"""player_transactions persistence: append-only, idempotent re-runs via the
UNIQUE (team_id, transaction_date, description) constraint (see
db/migrations/0020_player_transactions.sql).

One row per call, not a bulk executemany like plays_repo -- ON CONFLICT DO
NOTHING ... RETURNING id lets each insert report back whether it was a real
insert or a skipped duplicate, which the pipeline needs for accurate
backfill counts (plays_repo can't do this today because psycopg's
executemany doesn't reliably expose per-row RETURNING results across
drivers; a per-season transactions backfill is small enough -- low hundreds
of rows -- that row-at-a-time isn't a real cost).
"""

from __future__ import annotations

from datetime import datetime

from psycopg import Connection

_INSERT_TRANSACTION = """
INSERT INTO player_transactions (
    transaction_date, team_id, raw_team_name, player_id, raw_player_name,
    transaction_type, description, source
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (team_id, transaction_date, description) DO NOTHING
RETURNING id
"""


def insert_transaction(
    conn: Connection,
    *,
    transaction_date: datetime,
    team_id: int | None,
    raw_team_name: str,
    player_id: int | None,
    raw_player_name: str | None,
    transaction_type: str,
    description: str,
    source: str,
) -> bool:
    """Insert one transaction row. Returns True if a new row was inserted,
    False if skipped as an already-known duplicate (see module docstring).
    """
    row = conn.execute(
        _INSERT_TRANSACTION,
        (
            transaction_date,
            team_id,
            raw_team_name,
            player_id,
            raw_player_name,
            transaction_type,
            description,
            source,
        ),
    ).fetchone()
    return row is not None
