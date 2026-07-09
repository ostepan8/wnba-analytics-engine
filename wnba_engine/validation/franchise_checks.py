"""Franchise-identity checks -- catches non-franchise teams (All-Star
rosters, national teams, club exhibition opponents) leaking into games
that are tagged as counting toward a real season. This is the class of
bug that let 4 WNBA All-Star games (2022-2025) get ingested as
regular-season: "Team Wilson"/"Team Clark"/etc. are captain-picked
exhibition squads, not real franchises, so their wins/losses must never
count toward a team's record. See teams.is_franchise (migration 0010).
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.validation import CheckResult
from wnba_engine.validation._shared import build_check_result

_NON_FRANCHISE_IN_REGULAR_SEASON_SQL = """
SELECT g.id, g.season, th.name AS home_name, ta.name AS away_name
FROM games g
JOIN teams th ON th.id = g.home_team_id
JOIN teams ta ON ta.id = g.away_team_id
WHERE g.season_type = 'regular-season'
  AND (NOT th.is_franchise OR NOT ta.is_franchise)
"""


def check_non_franchise_team_in_regular_season(conn: Connection) -> CheckResult:
    """A regular-season game must be played between two recognized
    franchises. Anything else (All-Star exhibition, a national-team
    friendly mistagged upstream, etc.) is a season_type bug: it either
    belongs to SeasonType.OTHER/PRESEASON, or a non-franchise team was
    wrongly created instead of resolving to the real one.
    """
    rows = conn.execute(_NON_FRANCHISE_IN_REGULAR_SEASON_SQL).fetchall()
    return build_check_result(
        name="non_franchise_team_in_regular_season",
        description="games.season_type='regular-season' only involves recognized franchises",
        rows=rows,
        formatter=lambda r: f"game={r[0]} season={r[1]}: {r[2]!r} vs {r[3]!r}",
    )
