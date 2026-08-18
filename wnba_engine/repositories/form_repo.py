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
   AND g.season_type IN ('regular-season', 'post-season')
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
        AND g.season_type IN ('regular-season', 'post-season')
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


# Everything about a team going into a game: record, form, scoring, rest.
#
# `before` makes this point-in-time, the same as the player windows. Previewing
# a completed game with a record that already includes it is the same leak in a
# different table.
_TEAM_FORM = """
WITH played AS (
    SELECT g.id, g.start_time,
           t.id AS team_id,
           (g.home_team_id = t.id) AS is_home,
           CASE WHEN g.home_team_id = t.id THEN g.home_score ELSE g.away_score END AS scored,
           CASE WHEN g.home_team_id = t.id THEN g.away_score ELSE g.home_score END AS allowed,
           row_number() OVER (PARTITION BY t.id ORDER BY g.start_time DESC) AS recency
      FROM teams t
      JOIN games g
        ON (g.home_team_id = t.id OR g.away_team_id = t.id)
     WHERE t.id = ANY(%(team_ids)s)
       AND g.season = %(season)s
       AND g.season_type IN ('regular-season', 'post-season')
       AND g.status = 'final'
       AND g.home_score IS NOT NULL
       AND (%(before)s::timestamptz IS NULL OR g.start_time < %(before)s::timestamptz)
)
SELECT team_id,
       count(*)                                              AS games,
       count(*) FILTER (WHERE scored > allowed)               AS wins,
       count(*) FILTER (WHERE scored < allowed)               AS losses,
       round(avg(scored)::numeric, 1)                         AS points_for,
       round(avg(allowed)::numeric, 1)                        AS points_against,
       round(avg(scored) FILTER (WHERE recency <= 5)::numeric, 1)   AS points_for_l5,
       round(avg(allowed) FILTER (WHERE recency <= 5)::numeric, 1)  AS points_against_l5,
       count(*) FILTER (WHERE recency <= 5 AND scored > allowed)     AS wins_l5,
       count(*) FILTER (WHERE recency <= 10 AND scored > allowed)    AS wins_l10,
       count(*) FILTER (WHERE recency <= 10)                         AS games_l10,
       max(start_time) FILTER (WHERE recency = 1)                    AS last_game_at
  FROM played
 GROUP BY team_id
"""

# The most recent status for every player a team currently has on its report.
#
# DISTINCT ON the latest capture per player: injury_reports is an append-only
# snapshot every two hours, so a raw select returns the same knee a hundred
# times. Cleared players are dropped -- a report listing everyone who was ever
# hurt is not an injury report.
_CURRENT_INJURIES = """
SELECT DISTINCT ON (i.player_id)
       i.player_id, p.full_name, p.position, i.team_id, t.abbreviation,
       i.status, i.injury_type, i.side, i.return_date,
       i.short_comment, i.reported_at, i.captured_at, i.source
  FROM injury_reports i
  JOIN players p ON p.id = i.player_id
  LEFT JOIN teams t ON t.id = i.team_id
 WHERE (%(team_ids)s::bigint[] IS NULL OR i.team_id = ANY(%(team_ids)s))
   AND i.captured_at >= now() - interval '3 days'
 ORDER BY i.player_id,
          -- The league's own report wins over ESPN's, even when ESPN's capture
          -- is newer. ESPN publishes only Out/Day-To-Day for the WNBA and the
          -- two disagree: on 2026-08-17 ESPN had Jessica Shepard Out while the
          -- league's 04:00 PM report had her Probable. Sorting by recency alone
          -- would let the coarser, wrong answer overwrite the filed one every
          -- time ESPN happens to poll last.
          (i.source = 'wnba_official') DESC,
          i.captured_at DESC
"""


def fetch_team_form(
    conn: Connection, team_ids: list[int], *, season: int, before: str | None = None
) -> dict[int, dict[str, Any]]:
    """Record, scoring and recent form for several teams, keyed by team id."""
    if not team_ids:
        return {}
    rows = _all(
        conn, _TEAM_FORM, {"team_ids": team_ids, "season": season, "before": before}
    )
    return {int(row["team_id"]): row for row in rows}


def fetch_current_injuries(
    conn: Connection, team_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """Latest reported status per player, most recent capture wins."""
    return _all(conn, _CURRENT_INJURIES, {"team_ids": team_ids})


# Everyone currently on a team's injury report, paired with what she has
# actually been producing this season.
#
# The report alone says who; this says what is missing. "Three out" is the same
# headline for three bench players as for a 34-minute leading scorer, and only
# one of those moves a total.
#
# Season averages are deduped the same way the roster is: player_game_stats
# holds one row per (game, player, SOURCE), so a plain avg() would weight any
# game covered by two providers twice.
_INJURY_IMPACT = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (s.player_id, s.game_id)
           s.player_id, s.game_id, s.team_id,
           s.points, s.rebounds, s.assists, s.minutes
      FROM player_game_stats s
      JOIN games g ON g.id = s.game_id
     WHERE g.season = %(season)s
        AND g.season_type IN ('regular-season', 'post-season')
       AND s.team_id = ANY(%(team_ids)s)
       AND s.did_not_play IS NOT TRUE
     ORDER BY s.player_id, s.game_id,
              CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
),
season_avg AS (
    SELECT player_id, team_id,
           count(*)      AS games_played,
           avg(points)   AS points,
           avg(rebounds) AS rebounds,
           avg(assists)  AS assists,
           avg(minutes)  AS minutes
      FROM one_row_per_game
     GROUP BY player_id, team_id
),
current_status AS (
    SELECT DISTINCT ON (i.player_id)
           i.player_id, i.team_id, i.status, i.source,
           i.injury_type, i.short_comment
      FROM injury_reports i
     WHERE i.team_id = ANY(%(team_ids)s)
       AND i.captured_at >= now() - interval '3 days'
     -- Same source preference as _CURRENT_INJURIES: the league's own filing
     -- beats ESPN's coarser Out/Day-To-Day even when ESPN polled more recently.
     ORDER BY i.player_id, (i.source = 'wnba_official') DESC, i.captured_at DESC
)
SELECT c.player_id, p.full_name, p.position, c.team_id,
       c.status, c.source, c.injury_type, c.short_comment,
       coalesce(a.games_played, 0)         AS games_played,
       round(a.minutes::numeric, 1)        AS minutes,
       round(a.points::numeric, 1)         AS points,
       round(a.rebounds::numeric, 1)       AS rebounds,
       round(a.assists::numeric, 1)        AS assists
  FROM current_status c
  JOIN players p ON p.id = c.player_id
  LEFT JOIN season_avg a
         ON a.player_id = c.player_id AND a.team_id = c.team_id
 ORDER BY c.team_id, a.minutes DESC NULLS LAST
"""


def fetch_injury_impact(
    conn: Connection, team_ids: list[int], *, season: int
) -> dict[int, list[dict[str, Any]]]:
    """Listed players and their season production, keyed by team id."""
    if not team_ids:
        return {}
    rows = _all(conn, _INJURY_IMPACT, {"team_ids": team_ids, "season": season})
    by_team: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_team.setdefault(int(row["team_id"]), []).append(row)
    return by_team


# How many of the team's own most recent games a player has missed, counting
# back from the newest until the first one she actually played.
#
# A season average next to "Out" invites reading it as what tonight loses --
# but a player out 25 games ago already had her absence baked into every
# number on this page (the team's own recent form most of all), while a
# player who just went down has not. The stat is not what changes; how long
# it has been true is.
_PLAYERS_GAMES_MISSED = """
WITH team_games AS (
    SELECT g.id AS game_id,
           row_number() OVER (ORDER BY g.start_time DESC) AS rn
      FROM games g
     WHERE g.season = %(season)s
        AND g.season_type IN ('regular-season', 'post-season')
       AND g.status = 'final'
       AND %(team_id)s::bigint IN (g.home_team_id, g.away_team_id)
),
total AS (
    SELECT count(*) AS n FROM team_games
),
first_played AS (
    SELECT s.player_id, min(tg.rn) AS rn
      FROM player_game_stats s
      JOIN team_games tg ON tg.game_id = s.game_id
     WHERE s.player_id = ANY(%(player_ids)s::bigint[])
       AND s.did_not_play IS NOT TRUE
     GROUP BY s.player_id
)
SELECT pid AS player_id,
       -- Never played this season at all: missed every game the team has
       -- final so far, not "no data" -- coalesce to one past the total.
       coalesce(fp.rn, t.n + 1) - 1 AS games_missed
  FROM unnest(%(player_ids)s::bigint[]) AS pid
  LEFT JOIN first_played fp ON fp.player_id = pid
 CROSS JOIN total t
"""


def fetch_games_missed(
    conn: Connection, team_id: int, player_ids: list[int], *, season: int
) -> dict[int, int]:
    """Consecutive games missed, counting back from the team's most recent
    final game -- the current absence streak, not a season-long DNP total."""
    if not player_ids:
        return {}
    rows = _all(
        conn,
        _PLAYERS_GAMES_MISSED,
        {"team_id": team_id, "player_ids": player_ids, "season": season},
    )
    return {int(row["player_id"]): int(row["games_missed"]) for row in rows}
