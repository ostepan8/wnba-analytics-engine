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


#: Regular-season games each franchise is scheduled to play, by season.
#: Published lengths: 36 (2022), 40 (2023-24), 44 (2025). 2026 is omitted
#: because it is still in progress -- a mid-season count is not a violation.
SCHEDULED_GAMES: dict[int, int] = {2022: 36, 2023: 40, 2024: 40, 2025: 44}

_GAME_COUNT_SQL = """
SELECT g.season, t.name, count(*) AS played
FROM games g
JOIN teams t ON t.id IN (g.home_team_id, g.away_team_id)
WHERE g.season = ANY(%(seasons)s::int[])
  AND g.season_type = 'regular-season'
  AND g.status = 'final'
  AND t.is_franchise
GROUP BY 1, 2
"""


def check_regular_season_game_counts(conn: Connection) -> CheckResult:
    """Every franchise plays exactly the published number of games.

    Found by checking our 2025 standings against Wikipedia: 11 of 13 teams
    matched, and the two that did not were one extra Fever win and one
    extra Lynx loss -- the SAME game. It is the Commissioner's Cup final
    (Indiana 74, Minnesota 59, 2025-07-01), which ESPN reports with
    season_type 'regular-season' but which does NOT count toward
    regular-season standings.

    It is systematic: every season has exactly two teams one game over, and
    they are that year's Cup finalists (2022 LV/CHI, 2023 LV/NY, 2024
    MIN/NY, 2025 IND/MIN). Left in the data deliberately -- the game was
    really played, its box score is real, and dropping it would lose a
    genuine result -- but any standings or season-to-date figure derived
    from `season_type='regular-season'` is off by one for eight
    team-seasons, and nothing else surfaces that.
    """
    seasons = sorted(SCHEDULED_GAMES)
    rows = conn.execute(_GAME_COUNT_SQL, {"seasons": seasons}).fetchall()
    violations = [
        (season, name, played, SCHEDULED_GAMES[season])
        for season, name, played in rows
        if played != SCHEDULED_GAMES[season]
    ]
    return build_check_result(
        name="regular_season_game_counts",
        description="each franchise plays exactly the published regular-season schedule",
        rows=violations,
        formatter=lambda r: f"{r[0]} {r[1]}: {r[2]} games, scheduled {r[3]}",
        # The key encodes the COUNT, so a team drifting to 38 games would
        # fail again rather than inheriting the acknowledgement for 37.
        key_fn=lambda r: f"{r[0]}/{r[1]}:{r[2]}",
    )
