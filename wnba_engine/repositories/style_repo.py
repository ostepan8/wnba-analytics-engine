"""Style-space vectors, read-only.

Both queries deliberately aggregate WHOLE SEASONS rather than respecting
a point-in-time boundary. That is safe here and would not be for a
feature build: this describes how a team or player played across a season
that has already happened, for comparison and description. It must never
be joined into a predictive frame -- a season aggregate contains the
games it would be used to predict, which is the exact leak
wnba_engine/features/ exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence

from psycopg import Connection

from wnba_engine.analysis.style import PLAYER_DIMENSIONS, TEAM_DIMENSIONS, StylePoint

#: Enough minutes that per-36 rates are not noise. A player with 200
#: minutes has rate stats dominated by a handful of possessions.
MIN_SEASON_MINUTES = 300

#: Enough games that a team's four factors reflect a style rather than a
#: hot streak.
MIN_TEAM_GAMES = 15


def load_player_points(
    conn: Connection, *, min_minutes: int = MIN_SEASON_MINUTES
) -> tuple[StylePoint, ...]:
    rows = conn.execute(
        f"""
        WITH rates AS (
            SELECT s.player_id, g.season, SUM(s.minutes) AS mins,
                36.0*SUM(s.points)/NULLIF(SUM(s.minutes),0)              AS pts36,
                36.0*SUM(s.rebounds)/NULLIF(SUM(s.minutes),0)            AS reb36,
                36.0*SUM(s.assists)/NULLIF(SUM(s.minutes),0)             AS ast36,
                36.0*SUM(s.three_pointers_made)/NULLIF(SUM(s.minutes),0) AS tpm36,
                36.0*SUM(s.steals)/NULLIF(SUM(s.minutes),0)              AS stl36,
                36.0*SUM(s.blocks)/NULLIF(SUM(s.minutes),0)              AS blk36,
                36.0*SUM(s.turnovers)/NULLIF(SUM(s.minutes),0)           AS tov36,
                SUM(s.three_pointers_attempted)::numeric
                    /NULLIF(SUM(s.field_goals_attempted),0)              AS three_share,
                SUM(s.free_throws_attempted)::numeric
                    /NULLIF(SUM(s.field_goals_attempted),0)              AS ft_rate,
                SUM(s.offensive_rebounds)::numeric
                    /NULLIF(SUM(s.rebounds),0)                           AS oreb_share
            FROM player_game_stats s JOIN games g ON g.id = s.game_id
            WHERE s.source = 'espn' AND NOT s.did_not_play
              AND g.season_type IN ('regular-season','post-season')
            GROUP BY 1,2 HAVING SUM(s.minutes) >= %(min_minutes)s
        ), adv AS (
            SELECT pa.player_id, g.season,
                AVG(pa.usage_percentage)              AS usage,
                AVG(pa.true_shooting_percentage)      AS ts,
                AVG(pa.assist_percentage)             AS astpct,
                AVG(pa.rebound_percentage)            AS rebpct
            FROM player_advanced_stats pa JOIN games g ON g.id = pa.game_id
            WHERE g.season_type IN ('regular-season','post-season')
            GROUP BY 1,2
        )
        SELECT p.full_name, r.player_id, r.season,
               {', '.join('r.' + d if d not in ('usage','ts','astpct','rebpct') else 'a.' + d
                          for d in PLAYER_DIMENSIONS)}
        FROM rates r
        JOIN players p ON p.id = r.player_id
        JOIN adv a ON a.player_id = r.player_id AND a.season = r.season
        WHERE a.usage IS NOT NULL AND r.three_share IS NOT NULL AND r.oreb_share IS NOT NULL
        ORDER BY p.full_name, r.season
        """,
        {"min_minutes": min_minutes},
    ).fetchall()
    return _to_points(rows, len(PLAYER_DIMENSIONS))


def load_team_points(
    conn: Connection, *, min_games: int = MIN_TEAM_GAMES
) -> tuple[StylePoint, ...]:
    rows = conn.execute(
        """
        WITH adv AS (
            SELECT ta.team_id, g.season,
                AVG(ta.pace) pace, AVG(ta.effective_field_goal_percentage) efg,
                AVG(ta.turnover_ratio) tov, AVG(ta.offensive_rebound_percentage) oreb,
                AVG(ta.free_throw_attempt_rate) ftr, AVG(ta.assist_percentage) ast,
                AVG(ta.opp_effective_field_goal_percentage) d_efg,
                AVG(ta.opp_team_turnover_percentage) d_tov,
                AVG(ta.opp_offensive_rebound_percentage) d_oreb,
                AVG(ta.opp_free_throw_attempt_rate) d_ftr
            FROM team_advanced_stats ta JOIN games g ON g.id = ta.game_id
            WHERE g.season_type IN ('regular-season','post-season')
            GROUP BY 1,2 HAVING COUNT(*) >= %(min_games)s
        ), zone AS (
            SELECT team_id, season,
                (restricted_area_fga + in_the_paint_non_ra_fga)::numeric
                    / NULLIF(restricted_area_fga+in_the_paint_non_ra_fga+mid_range_fga
                             +corner_3_fga+above_the_break_3_fga,0) paint_rate,
                (corner_3_fga + above_the_break_3_fga)::numeric
                    / NULLIF(restricted_area_fga+in_the_paint_non_ra_fga+mid_range_fga
                             +corner_3_fga+above_the_break_3_fga,0) three_rate,
                mid_range_fga::numeric
                    / NULLIF(restricted_area_fga+in_the_paint_non_ra_fga+mid_range_fga
                             +corner_3_fga+above_the_break_3_fga,0) mid_rate
            FROM team_shot_zone_stats
        )
        SELECT t.name, a.team_id, a.season,
               a.pace, a.efg, a.tov, a.oreb, a.ftr, a.ast,
               a.d_efg, a.d_tov, a.d_oreb, a.d_ftr,
               z.paint_rate, z.three_rate, z.mid_rate
        FROM adv a
        JOIN teams t ON t.id = a.team_id
        JOIN zone z ON z.team_id = a.team_id AND z.season = a.season
        WHERE z.paint_rate IS NOT NULL
        ORDER BY t.name, a.season
        """,
        {"min_games": min_games},
    ).fetchall()
    return _to_points(rows, len(TEAM_DIMENSIONS))


def _to_points(rows: Sequence[tuple], width: int) -> tuple[StylePoint, ...]:
    return tuple(
        StylePoint(
            label=f"{r[0]} {r[2]}",
            entity_id=int(r[1]),
            season=int(r[2]),
            coordinates=tuple(float(v) for v in r[3 : 3 + width]),
        )
        for r in rows
        if all(v is not None for v in r[3 : 3 + width])
    )
