"""Cross-source and cross-table consistency checks. Each compares two
independently-derived integers that should agree exactly -- a mismatch
means a parsing bug or a bad crosswalk match, not floating-point noise.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.validation import CheckResult
from wnba_engine.validation._shared import build_check_result

_TEAM_SCORE_VS_BOX_SCORE_SQL = """
SELECT g.id, g.home_score, g.away_score,
       SUM(CASE WHEN pgs.team_id = g.home_team_id THEN pgs.points ELSE 0 END) AS home_sum,
       SUM(CASE WHEN pgs.team_id = g.away_team_id THEN pgs.points ELSE 0 END) AS away_sum
FROM games g
JOIN player_game_stats pgs ON pgs.game_id = g.id AND pgs.source = 'espn'
WHERE g.status = 'final'
GROUP BY g.id, g.home_score, g.away_score
HAVING SUM(CASE WHEN pgs.team_id = g.home_team_id THEN pgs.points ELSE 0 END) <> g.home_score
    OR SUM(CASE WHEN pgs.team_id = g.away_team_id THEN pgs.points ELSE 0 END) <> g.away_score
"""


def check_team_box_score_matches_final_score(conn: Connection) -> CheckResult:
    """SUM(player_game_stats.points) per side must equal games.home_score/
    away_score -- these come from two DIFFERENT ESPN endpoints (box score
    vs scoreboard), so a mismatch is a real ingestion bug, not redundant
    data.
    """
    rows = conn.execute(_TEAM_SCORE_VS_BOX_SCORE_SQL).fetchall()
    return build_check_result(
        name="team_box_score_matches_final_score",
        description="SUM(player points) per team equals games.home_score/away_score",
        rows=rows,
        formatter=lambda r: f"game={r[0]} score={r[1]}-{r[2]} but player-stat sums={r[3]}-{r[4]}",
    )


_TEAM_TOTALS_VS_PLAYER_SUMS_SQL = """
SELECT tgs.game_id, tgs.team_id, tgs.source,
       tgs.field_goals_made, SUM(pgs.field_goals_made) AS fgm_sum,
       tgs.rebounds, SUM(pgs.rebounds) AS reb_sum,
       tgs.assists, SUM(pgs.assists) AS ast_sum,
       tgs.turnovers, SUM(pgs.turnovers) AS tov_sum
FROM team_game_stats tgs
JOIN player_game_stats pgs
    ON pgs.game_id = tgs.game_id AND pgs.team_id = tgs.team_id AND pgs.source = tgs.source
GROUP BY tgs.game_id, tgs.team_id, tgs.source,
         tgs.field_goals_made, tgs.rebounds, tgs.assists, tgs.turnovers
HAVING tgs.field_goals_made <> SUM(pgs.field_goals_made)
    OR tgs.rebounds <> SUM(pgs.rebounds)
    OR tgs.assists <> SUM(pgs.assists)
    OR tgs.turnovers <> SUM(pgs.turnovers)
"""


def check_team_totals_match_player_sums(conn: Connection) -> CheckResult:
    """team_game_stats and player_game_stats totals must agree PER SOURCE
    (FGM, rebounds, assists, turnovers), or one of a given provider's two
    parsers (team-level vs player-level) has a bug.

    GROUP BY must include tgs.source, not just the stat columns: verified
    live that once a second box-score source (balldontlie) exists
    alongside ESPN for the same game and both correctly report identical
    real totals, grouping on the stat values alone collapsed the two
    same-valued-but-different-source team rows into one group -- summing
    player rows from BOTH sources together and reporting e.g. "32 vs 64"
    as a false violation on totally correct, cross-source-agreeing data.
    """
    rows = conn.execute(_TEAM_TOTALS_VS_PLAYER_SUMS_SQL).fetchall()
    return build_check_result(
        name="team_totals_match_player_sums",
        description="team_game_stats totals equal SUM() of that team's player_game_stats rows",
        rows=rows,
        formatter=lambda r: (
            f"game={r[0]} team={r[1]} source={r[2]} fgm(team/sum)={r[3]}/{r[4]} reb={r[5]}/{r[6]} "
            f"ast={r[7]}/{r[8]} tov={r[9]}/{r[10]}"
        ),
    )


_PLAYS_FINAL_SCORE_VS_GAME_SCORE_SQL = """
SELECT g.id, g.home_score, g.away_score, eg.home_score, eg.away_score
FROM games g
JOIN game_plays eg ON eg.game_id = g.id AND eg.play_type = 'End Game'
WHERE g.status = 'final'
AND (g.home_score <> eg.home_score OR g.away_score <> eg.away_score)
"""


def check_plays_final_score_matches_game_score(conn: Connection) -> CheckResult:
    """The "End Game" play-by-play row's running score (balldontlie) must
    match games.home_score/away_score (ESPN) -- two entirely different
    providers agreeing on the same final score is a strong correctness
    signal; a mismatch means balldontlie's own play-by-play disagrees
    with ESPN's scoreboard on the final score, or our game crosswalk
    matched the wrong game.

    Anchored on the "End Game" play type, NOT the highest sequence
    number: verified live that balldontlie's "order" field isn't reliably
    monotonic -- some early-game plays (e.g. a period-1 jumpball) can get
    a spuriously high sequence number appended after the real final play,
    which made a naive ORDER BY sequence DESC LIMIT 1 report ~100 false
    mismatches where the "last row" was actually from early in the game.
    Games missing an "End Game" row entirely (rare, ~3 of 1242) are
    outside this check's scope -- there's no anchor to compare against.
    """
    rows = conn.execute(_PLAYS_FINAL_SCORE_VS_GAME_SCORE_SQL).fetchall()
    return build_check_result(
        name="plays_final_score_matches_game_score",
        description="game_plays' last row score matches games.home_score/away_score",
        rows=rows,
        formatter=lambda r: (
            f"game={r[0]} games_score={r[1]}-{r[2]} plays_final_score={r[3]}-{r[4]}"
        ),
    )
