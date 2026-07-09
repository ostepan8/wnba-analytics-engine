"""Sportsbook odds persistence (balldontlie /odds and /odds/player_props).

Append-only, not upserted -- see db/migrations/0014_balldontlie_odds.sql for
why: UNIQUE(external_id, captured_at) with ON CONFLICT DO NOTHING makes a
re-run over an unchanged window a no-op, while genuine odds movement (a new
source-side updated_at for the same external_id) lands as a new history row.
Both insert functions return whether a row was actually inserted, so
callers (wnba_engine/pipeline/balldontlie_odds_ingest.py,
balldontlie_player_prop_odds_ingest.py) can distinguish "no-op re-run" from
"new row" in their result counters.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.odds import GameOddsRow, PlayerPropOddsRow

_INSERT_GAME_ODDS = """
INSERT INTO sportsbook_game_odds (
    source, external_id, game_id, vendor,
    spread_home_value, spread_home_odds, spread_away_value, spread_away_odds,
    moneyline_home_odds, moneyline_away_odds,
    total_value, total_over_odds, total_under_odds,
    captured_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (external_id, captured_at) DO NOTHING
"""


def insert_game_odds(
    conn: Connection,
    *,
    game_id: int,
    source: str,
    row: GameOddsRow,
) -> bool:
    cursor = conn.execute(
        _INSERT_GAME_ODDS,
        (
            source,
            row.external_id,
            game_id,
            row.vendor,
            row.spread_home_value,
            row.spread_home_odds,
            row.spread_away_value,
            row.spread_away_odds,
            row.moneyline_home_odds,
            row.moneyline_away_odds,
            row.total_value,
            row.total_over_odds,
            row.total_under_odds,
            row.updated_at,
        ),
    )
    return cursor.rowcount > 0


_INSERT_PLAYER_PROP_ODDS = """
INSERT INTO sportsbook_player_prop_odds (
    source, external_id, game_id, player_id, vendor,
    prop_type, line_value, market_type, odds, over_odds, under_odds,
    captured_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (external_id, captured_at) DO NOTHING
"""


def insert_player_prop_odds(
    conn: Connection,
    *,
    game_id: int,
    player_id: int,
    source: str,
    row: PlayerPropOddsRow,
) -> bool:
    cursor = conn.execute(
        _INSERT_PLAYER_PROP_ODDS,
        (
            source,
            row.external_id,
            game_id,
            player_id,
            row.vendor,
            row.prop_type,
            row.line_value,
            row.market_type,
            row.odds,
            row.over_odds,
            row.under_odds,
            row.updated_at,
        ),
    )
    return cursor.rowcount > 0
