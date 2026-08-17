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
#: Published lengths: 36 (2022), 40 (2023-24), 44 (2025-26).
#:
#: 2026 is included, which it was not before. Its absence is what let an
#: incomplete SCHEDULE go unnoticed: the played-count check below skips
#: in-progress seasons by design, so nothing was watching whether the FUTURE
#: fixtures had been ingested at all. They had not -- the table held 33-37 games
#: per team of a 44-game season, which made every remaining game invisible and
#: reported eleven teams as mathematically eliminated when only two were.
SCHEDULED_GAMES: dict[int, int] = {2022: 36, 2023: 40, 2024: 40, 2025: 44, 2026: 44}

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
    # Only seasons with nothing left to play. A mid-season count is not a
    # violation, and 2026 now appears in SCHEDULED_GAMES for the completeness
    # check below.
    seasons = _completed_seasons(conn)
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


_COMPLETED_SEASONS_SQL = """
SELECT season
  FROM games
 WHERE season = ANY(%(seasons)s::int[])
   AND season_type = 'regular-season'
 GROUP BY season
HAVING count(*) FILTER (WHERE status <> 'final') = 0
"""

_SCHEDULE_KNOWN_SQL = """
SELECT g.season, t.name, count(*) AS known
FROM games g
JOIN teams t ON t.id IN (g.home_team_id, g.away_team_id)
WHERE g.season = ANY(%(seasons)s::int[])
  AND g.season_type = 'regular-season'
  AND t.is_franchise
GROUP BY 1, 2
"""


def _completed_seasons(conn: Connection) -> list[int]:
    rows = conn.execute(
        _COMPLETED_SEASONS_SQL, {"seasons": sorted(SCHEDULED_GAMES)}
    ).fetchall()
    return sorted(season for (season,) in rows)


def check_schedule_is_complete(conn: Connection) -> CheckResult:
    """Every franchise's WHOLE schedule is in the table, played or not.

    This exists because of a failure that looked like a modelling bug and was a
    data one. `sync-recent` only reaches seven days ahead, so fixtures beyond
    that were never ingested: in August 2026 the table held 33-37 regular-season
    games per team out of 44. Nothing was wrong with any row -- the missing ones
    simply did not exist.

    The consequence was not a blank cell. Games remaining is derived by counting
    scheduled games, so every team appeared to have none left, and the playoff
    page reported eleven teams as mathematically eliminated when the true number
    was two. A gap in future data became a confident false statement about the
    present.

    Counts games at ANY status, which is what separates this from
    check_regular_season_game_counts: that one asks whether the right number of
    games were PLAYED and can only run on a finished season, while this one asks
    whether we know about all of them yet -- the question that matters while a
    season is still going.
    """
    seasons = sorted(SCHEDULED_GAMES)
    rows = conn.execute(_SCHEDULE_KNOWN_SQL, {"seasons": seasons}).fetchall()
    violations = [
        (season, name, known, SCHEDULED_GAMES[season])
        for season, name, known in rows
        if known < SCHEDULED_GAMES[season]
    ]
    return build_check_result(
        name="schedule_is_complete",
        description="every franchise's full regular-season schedule has been ingested",
        rows=violations,
        formatter=lambda r: (
            f"{r[0]} {r[1]}: only {r[2]} of {r[3]} games known -- "
            f"future fixtures are missing, so games-remaining is understated"
        ),
        key_fn=lambda r: f"{r[0]}/{r[1]}:{r[2]}",
    )
