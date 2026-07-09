"""Official standings persistence.

Two tables, written together by the same ingestion run, for two different
read patterns:

- team_standings: upserted (not append-only) -- a re-run overwrites the
  same (team, season, source) row with the CURRENT snapshot, since
  standings values (wins, losses, games_behind, ...) genuinely change on
  every re-fetch, unlike the immutable per-game stats other balldontlie
  tables store. See db/migrations/0013_standings.sql.
- team_standings_history: append-only -- every ingestion run inserts a new
  timestamped snapshot row rather than overwriting, so trends over the
  season can be reconstructed later. See db/migrations/0015_standings_history.sql.
"""

from __future__ import annotations

from datetime import datetime

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


_SELECT_LATEST_HISTORY = """
SELECT conference, wins, losses, win_percentage, games_behind,
       home_record, away_record, conference_record, playoff_seed
FROM team_standings_history
WHERE team_id = %s AND season = %s AND source = %s
ORDER BY captured_at DESC
LIMIT 1
"""

_INSERT_HISTORY = """
INSERT INTO team_standings_history (
    team_id, season, source, conference, wins, losses, win_percentage,
    games_behind, home_record, away_record, conference_record, playoff_seed,
    captured_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""


def insert_standings_history(
    conn: Connection,
    *,
    team_id: int,
    season: int,
    source: str,
    row: StandingsRow,
    captured_at: datetime,
) -> bool:
    """Append a standings snapshot row. Returns True if inserted, False if
    skipped as a no-op duplicate.

    Dedup safeguard: if the most recent history row for this
    (team_id, season, source) already has IDENTICAL values to `row`, skip
    the insert -- a backfill run where nothing changed since the last
    capture would otherwise accumulate meaningless duplicate rows forever
    (e.g. running this hourly during an off day). This does NOT affect
    upsert_standings, which always runs regardless -- the current-state
    table's freshness (updated_at) shouldn't depend on whether the values
    changed.
    """
    latest = conn.execute(_SELECT_LATEST_HISTORY, (team_id, season, source)).fetchone()
    if latest is not None and _matches_row(latest, row):
        return False
    conn.execute(
        _INSERT_HISTORY,
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
            captured_at,
        ),
    )
    return True


def _matches_row(latest: tuple[object, ...], row: StandingsRow) -> bool:
    (
        conference,
        wins,
        losses,
        win_percentage,
        games_behind,
        home_record,
        away_record,
        conference_record,
        playoff_seed,
    ) = latest
    return (
        conference == row.conference
        and wins == row.wins
        and losses == row.losses
        and float(win_percentage) == row.win_percentage
        and float(games_behind) == row.games_behind
        and home_record == row.home_record
        and away_record == row.away_record
        and conference_record == row.conference_record
        and playoff_seed == row.playoff_seed
    )
