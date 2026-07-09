"""Official standings persistence. Upserted (not append-only): a re-run
overwrites the same (team, season, source) row with the CURRENT snapshot --
standings values (wins, losses, games_behind, ...) genuinely change on every
re-fetch, unlike the immutable per-game stats other balldontlie tables
store. See db/migrations/0013_standings.sql.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.standings import StandingsRow

_UPSERT_STANDINGS = """
INSERT INTO team_standings (
    team_id, season, source, conference, wins, losses, win_percentage,
    games_behind, home_record, away_record, conference_record, playoff_seed
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (team_id, season, source) DO UPDATE SET
    conference = EXCLUDED.conference,
    wins = EXCLUDED.wins,
    losses = EXCLUDED.losses,
    win_percentage = EXCLUDED.win_percentage,
    games_behind = EXCLUDED.games_behind,
    home_record = EXCLUDED.home_record,
    away_record = EXCLUDED.away_record,
    conference_record = EXCLUDED.conference_record,
    playoff_seed = EXCLUDED.playoff_seed,
    updated_at = now()
"""


def upsert_standings(
    conn: Connection,
    *,
    team_id: int,
    season: int,
    source: str,
    row: StandingsRow,
) -> None:
    conn.execute(
        _UPSERT_STANDINGS,
        (
            team_id,
            season,
            source,
            row.conference,
            row.wins,
            row.losses,
            row.win_percentage,
            row.games_behind,
            row.home_record,
            row.away_record,
            row.conference_record,
            row.playoff_seed,
        ),
    )
