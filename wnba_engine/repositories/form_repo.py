"""Recent form, matchup history, and how often a line has actually been cleared.

This is the layer that turns a price into something a reader can weigh: a live
prop says "over 24.5 points"; what a reader wants is how often this player has
actually gone past 24.5, lately, and against this opponent.

Two disciplines run through all of it.

**Point-in-time.** Every window here is built from games ALREADY PLAYED before
the game in question. A "last 5" that quietly includes the game being previewed
is the single easiest way to manufacture an edge that does not exist, and it is
invisible in the output.

**Denominators travel with rates.** A 4-of-5 hit rate and a 40-of-50 hit rate
are not the same claim, and five games is noise at this level. Every count is
returned with the sample it came from so nothing can render a bare percentage.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from wnba_engine.repositories.analytics_repo import _all

# The stat behind each prop market, as it appears in a box score.
PROP_STAT_SQL: dict[str, str] = {
    "points": "s.points",
    "rebounds": "s.rebounds",
    "assists": "s.assists",
    "threes": "s.three_pointers_made",
    "points_rebounds_assists": "(s.points + s.rebounds + s.assists)",
}

# Per-game values for a set of players, newest first, with the opponent.
#
# One query for every player on a slate rather than one per player-market: a
# game carries ~50 props across ~20 players, and a query each would be fifty
# round trips to answer one page.
_PLAYER_STAT_HISTORY = """
SELECT DISTINCT ON (s.player_id, g.id)
       s.player_id, g.id AS game_id, g.start_time, g.season,
       s.points, s.rebounds, s.assists, s.three_pointers_made,
       (s.points + s.rebounds + s.assists) AS points_rebounds_assists,
       s.minutes, s.team_id,
       CASE WHEN g.home_team_id = s.team_id THEN g.away_team_id
            ELSE g.home_team_id END AS opponent_team_id,
       (g.home_team_id = s.team_id) AS is_home
  FROM player_game_stats s
  JOIN games g ON g.id = s.game_id
 WHERE s.player_id = ANY(%(player_ids)s)
   AND g.status = 'final'
   AND s.did_not_play IS NOT TRUE
   -- Point in time: only games finished BEFORE the one being looked at.
   AND (%(before)s::timestamptz IS NULL OR g.start_time < %(before)s::timestamptz)
   AND (%(season)s::int IS NULL OR g.season = %(season)s::int)
 ORDER BY s.player_id, g.id, g.start_time DESC,
          CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
"""

# Every previous meeting between two teams, newest first.
_HEAD_TO_HEAD = """
SELECT g.id, g.start_time, g.season, g.status,
       g.home_team_id, g.away_team_id, g.home_score, g.away_score,
       home.abbreviation AS home_abbr, away.abbreviation AS away_abbr
  FROM games g
  JOIN teams home ON home.id = g.home_team_id
  JOIN teams away ON away.id = g.away_team_id
 WHERE g.status = 'final'
   AND least(g.home_team_id, g.away_team_id) = least(%(a)s, %(b)s)
   AND greatest(g.home_team_id, g.away_team_id) = greatest(%(a)s, %(b)s)
   AND (%(before)s::timestamptz IS NULL OR g.start_time < %(before)s::timestamptz)
 ORDER BY g.start_time DESC
 LIMIT %(limit)s
"""

# What a team gives up to each position.
#
# Averaged per opposing player-game, not summed: a team that has played more
# games would otherwise look like a worse defence purely for having played.
# Ranked across the league by the caller, since a raw number means nothing
# without knowing whether 18 points to guards is good.
_DEFENSE_BY_POSITION = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (s.player_id, s.game_id)
           s.player_id, s.game_id, s.team_id, s.points, s.rebounds, s.assists,
           g.home_team_id, g.away_team_id
      FROM player_game_stats s
      JOIN games g ON g.id = s.game_id
     WHERE g.season = %(season)s
       AND g.status = 'final'
       AND s.did_not_play IS NOT TRUE
     ORDER BY s.player_id, s.game_id,
              CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
)
SELECT defender.id AS team_id, defender.abbreviation,
       p.position,
       count(DISTINCT r.game_id)                AS games,
       round(avg(r.points)::numeric, 1)         AS points_allowed,
       round(avg(r.rebounds)::numeric, 1)       AS rebounds_allowed,
       round(avg(r.assists)::numeric, 1)        AS assists_allowed
  FROM one_row_per_game r
  JOIN players p ON p.id = r.player_id
  JOIN teams defender
    ON defender.id = CASE WHEN r.team_id = r.home_team_id THEN r.away_team_id
                          ELSE r.home_team_id END
 WHERE p.position IS NOT NULL
   AND (%(team_id)s::bigint IS NULL OR defender.id = %(team_id)s::bigint)
 GROUP BY defender.id, defender.abbreviation, p.position
HAVING count(DISTINCT r.game_id) >= %(min_games)s
 ORDER BY defender.abbreviation, p.position
"""


def fetch_player_stat_history(
    conn: Connection,
    player_ids: list[int],
    *,
    before: str | None = None,
    season: int | None = None,
) -> list[dict[str, Any]]:
    """Per-game box-score lines for several players at once, newest first."""
    if not player_ids:
        return []
    return _all(
        conn,
        _PLAYER_STAT_HISTORY,
        {"player_ids": player_ids, "before": before, "season": season},
    )


def fetch_head_to_head(
    conn: Connection, team_a: int, team_b: int, *, before: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    return _all(
        conn, _HEAD_TO_HEAD, {"a": team_a, "b": team_b, "before": before, "limit": limit}
    )


def fetch_defense_by_position(
    conn: Connection, *, season: int, team_id: int | None = None, min_games: int = 5
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _DEFENSE_BY_POSITION,
        {"season": season, "team_id": team_id, "min_games": min_games},
    )
