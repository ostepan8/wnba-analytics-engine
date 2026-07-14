"""the-odds-api final-score persistence (odds_api_game_scores).

Append-only, not upserted -- see db/migrations/0021_odds_api_game_scores.sql
for why: UNIQUE(external_id, captured_at) with ON CONFLICT DO NOTHING makes
a re-run over an unchanged snapshot a no-op, while a genuine score
correction (a new source-side last_update for the same external_id) lands
as a new history row. Cross-check data only -- never touches
games.home_score/away_score.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.odds_api_scores import OddsApiGameScore

_INSERT_SCORE = """
INSERT INTO odds_api_game_scores (external_id, game_id, home_score, away_score, captured_at)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (external_id, captured_at) DO NOTHING
"""


def insert_score(conn: Connection, *, game_id: int, row: OddsApiGameScore) -> bool:
    cursor = conn.execute(
        _INSERT_SCORE,
        (row.external_id, game_id, row.home_score, row.away_score, row.captured_at),
    )
    return cursor.rowcount > 0
