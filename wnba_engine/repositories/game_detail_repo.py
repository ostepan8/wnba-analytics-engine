"""Everything known about one game, for the game-centric homepage.

Split from analytics_repo because these all answer the same question -- "what do
we have on this game?" -- and because two of them need a distinction that is
easy to get wrong.

**Offence versus defence is a JOIN, not a column.** shot_locations records who
took a shot, never who allowed it. A team's defensive shot chart is the set of
shots taken BY ITS OPPONENTS in games it played, which means resolving the
opponent per game rather than filtering on team_id. Getting this backwards
produces a chart that looks plausible and is the team's own offence again.

**A game's props are graded against the player's line in THAT game.** The
prop tables carry one row per vendor, so anything read straight out of them
counts a six-book game six times.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from wnba_engine.repositories.analytics_repo import _all

# Individual shots in one game, NOT binned.
#
# A season is 30,000 shots and has to be aggregated; one team in one game is
# about sixty-five. Binning those onto the same grid puts a single attempt in
# most cells, which renders as scattered noise -- the chart says nothing because
# there is nothing to average. At this scale the right mark is the shot itself:
# ~130 rows for a whole game is a trivial payload.
_GAME_SHOT_POINTS = """
SELECT s.loc_x, s.loc_y, s.made, s.shot_distance, s.shot_zone_basic,
       s.period, s.action_type, s.team_id,
       p.full_name AS player_name, p.id AS player_id,
       CASE WHEN s.shot_zone_basic LIKE '%%3%%' THEN 3 ELSE 2 END AS shot_value
  FROM shot_locations s
  LEFT JOIN players p ON p.id = s.player_id
 WHERE s.game_id = %(game_id)s
   AND (%(team_id)s::bigint IS NULL OR s.team_id = %(team_id)s::bigint)
   AND s.loc_y BETWEEN -50 AND 470
 ORDER BY s.period, s.seconds_remaining DESC NULLS LAST
"""

# Shots taken by one team in one game, binned. Kept for callers that want the
# aggregate rather than the individual attempts.
_GAME_SHOTS = """
SELECT (floor(s.loc_x / %(bin)s) * %(bin)s)::int AS x,
       (floor(s.loc_y / %(bin)s) * %(bin)s)::int AS y,
       count(*)                       AS attempts,
       count(*) FILTER (WHERE s.made) AS makes,
       sum(CASE WHEN s.made
                THEN CASE WHEN s.shot_zone_basic LIKE '%%3%%' THEN 3 ELSE 2 END
                ELSE 0 END)           AS points
  FROM shot_locations s
 WHERE s.game_id = %(game_id)s
   AND (%(team_id)s::bigint IS NULL OR s.team_id = %(team_id)s::bigint)
   AND s.loc_y BETWEEN -50 AND 470
 GROUP BY 1, 2
 ORDER BY 1, 2
"""

# Shots a team ALLOWED across a season: everything its opponents took against
# it. The opponent is resolved per game rather than filtered by team_id, which
# is the whole difference between a defensive chart and the team's own offence.
_SHOT_DEFENCE = """
SELECT (floor(s.loc_x / %(bin)s) * %(bin)s)::int AS x,
       (floor(s.loc_y / %(bin)s) * %(bin)s)::int AS y,
       count(*)                       AS attempts,
       count(*) FILTER (WHERE s.made) AS makes,
       sum(CASE WHEN s.made
                THEN CASE WHEN s.shot_zone_basic LIKE '%%3%%' THEN 3 ELSE 2 END
                ELSE 0 END)           AS points
  FROM shot_locations s
  JOIN games g ON g.id = s.game_id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   -- The defending team played in the game...
   AND %(team_id)s::bigint IN (g.home_team_id, g.away_team_id)
   -- ...and did NOT take the shot.
   AND s.team_id IS DISTINCT FROM %(team_id)s::bigint
   AND s.loc_y BETWEEN -50 AND 470
 GROUP BY 1, 2
 ORDER BY 1, 2
"""

_SHOT_DEFENCE_ZONES = """
SELECT s.shot_zone_basic AS zone,
       count(*)                       AS attempts,
       count(*) FILTER (WHERE s.made) AS makes,
       round(avg(s.shot_distance)::numeric, 1) AS avg_distance
  FROM shot_locations s
  JOIN games g ON g.id = s.game_id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   AND %(team_id)s::bigint IN (g.home_team_id, g.away_team_id)
   AND s.team_id IS DISTINCT FROM %(team_id)s::bigint
   AND s.shot_zone_basic IS NOT NULL
 GROUP BY 1
 ORDER BY 2 DESC
"""

# Same defensive set as _SHOT_DEFENCE, grouped by the opposing SHOOTER instead
# of court position -- who has actually gone off against this defence, not just
# where. s.team_id is the shooter's own team here (never the defending team, by
# the WHERE clause below), so it doubles as "which opponent" with no extra join.
_SHOT_DEFENCE_BY_PLAYER = """
SELECT s.player_id,
       p.full_name,
       t.abbreviation AS team_abbr,
       count(DISTINCT s.game_id)      AS games,
       count(*)                       AS attempts,
       count(*) FILTER (WHERE s.made) AS makes,
       sum(CASE WHEN s.made
                THEN CASE WHEN s.shot_zone_basic LIKE '%%3%%' THEN 3 ELSE 2 END
                ELSE 0 END)           AS points
  FROM shot_locations s
  JOIN games g ON g.id = s.game_id
  LEFT JOIN players p ON p.id = s.player_id
  LEFT JOIN teams t ON t.id = s.team_id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   AND %(team_id)s::bigint IN (g.home_team_id, g.away_team_id)
   AND s.team_id IS DISTINCT FROM %(team_id)s::bigint
   -- IS DISTINCT FROM treats NULL as distinct from everything, so a shot row
   -- with an unresolved team_id (an unmatched provider identity -- see the
   -- Kayla Alexander / Megan Gustafson class of bug) passed this filter for
   -- EVERY team_id queried, including the shooter's own team: querying that
   -- team's own defense leaked her whole season back in as if she'd gone off
   -- against herself. An unresolved shooter can't be attributed to either
   -- side of a matchup, so she's excluded outright rather than risk it again.
   AND s.team_id IS NOT NULL
   AND s.player_id IS NOT NULL
 GROUP BY s.player_id, p.full_name, t.abbreviation
HAVING count(*) >= %(min_attempts)s
 ORDER BY points DESC
 LIMIT %(limit)s
"""

# Every player prop posted for one game, one consensus line per player-market.
_GAME_PLAYER_PROPS = """
WITH per_market AS (
    SELECT o.player_id, o.prop_type,
           avg(o.line_value)        AS line,
           count(DISTINCT o.vendor) AS books,
           max(o.captured_at)       AS captured_at
      FROM sportsbook_player_prop_odds o
     WHERE o.game_id = %(game_id)s
       AND o.line_value IS NOT NULL
     GROUP BY o.player_id, o.prop_type
)
SELECT m.player_id, p.full_name, t.abbreviation AS team_abbr, t.id AS team_id,
       m.prop_type, round(m.line::numeric, 1) AS line, m.books, m.captured_at,
       s.points, s.rebounds, s.assists, s.three_pointers_made,
       CASE m.prop_type
            WHEN 'points'   THEN s.points
            WHEN 'rebounds' THEN s.rebounds
            WHEN 'assists'  THEN s.assists
            WHEN 'threes'   THEN s.three_pointers_made
            WHEN 'points_rebounds_assists'
                 THEN s.points + s.rebounds + s.assists
       END AS realized
  FROM per_market m
  JOIN players p ON p.id = m.player_id
  LEFT JOIN LATERAL (
      SELECT DISTINCT ON (pgs.player_id) pgs.*
        FROM player_game_stats pgs
       WHERE pgs.game_id = %(game_id)s AND pgs.player_id = m.player_id
       ORDER BY pgs.player_id,
                CASE pgs.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
  ) s ON TRUE
  LEFT JOIN teams t ON t.id = s.team_id
 ORDER BY m.prop_type, m.line DESC NULLS LAST
"""

# Which teams played, so a client can ask for each side's shots without a
# second round trip.
_GAME_TEAMS = """
SELECT g.home_team_id, g.away_team_id,
       home.abbreviation AS home_abbr, away.abbreviation AS away_abbr
  FROM games g
  JOIN teams home ON home.id = g.home_team_id
  JOIN teams away ON away.id = g.away_team_id
 WHERE g.id = %(game_id)s
"""


def fetch_game_shot_points(
    conn: Connection, game_id: int, *, team_id: int | None
) -> list[dict[str, Any]]:
    """Every shot in the game as its own row -- the right grain for one game."""
    return _all(conn, _GAME_SHOT_POINTS, {"game_id": game_id, "team_id": team_id})


def fetch_game_shots(
    conn: Connection, game_id: int, *, team_id: int | None, bin_size: int
) -> list[dict[str, Any]]:
    return _all(conn, _GAME_SHOTS, {"game_id": game_id, "team_id": team_id, "bin": bin_size})


def fetch_shot_defence(
    conn: Connection, team_id: int, *, season: int, bin_size: int
) -> list[dict[str, Any]]:
    return _all(conn, _SHOT_DEFENCE, {"team_id": team_id, "season": season, "bin": bin_size})


def fetch_shot_defence_zones(
    conn: Connection, team_id: int, *, season: int
) -> list[dict[str, Any]]:
    return _all(conn, _SHOT_DEFENCE_ZONES, {"team_id": team_id, "season": season})


def fetch_shot_defence_by_player(
    conn: Connection, team_id: int, *, season: int, min_attempts: int = 10, limit: int = 15
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _SHOT_DEFENCE_BY_PLAYER,
        {"team_id": team_id, "season": season, "min_attempts": min_attempts, "limit": limit},
    )


def fetch_game_player_props(conn: Connection, game_id: int) -> list[dict[str, Any]]:
    return _all(conn, _GAME_PLAYER_PROPS, {"game_id": game_id})


def fetch_game_teams(conn: Connection, game_id: int) -> dict[str, Any] | None:
    rows = _all(conn, _GAME_TEAMS, {"game_id": game_id})
    return rows[0] if rows else None
