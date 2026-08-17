-- Populate shot_locations.team_id, which has been NULL on every row since the
-- table was created.
--
-- The column exists, the INSERT names it, and the ingest passes a literal NULL
-- for it (wnba_engine/pipeline/wnba_stats_ingest.py::_shot_rows). Nothing ever
-- read it, so nothing ever noticed -- until a team shot chart asked for
-- `WHERE team_id = 7` and got zero rows back from 164,143 shots. A column that
-- is always NULL is indistinguishable from a working one until the first query
-- filters on it.
--
-- The team is recoverable because a shot already carries the game and the
-- player, and player_game_stats records which team a player played for in that
-- game. That table is keyed (game_id, player_id, SOURCE) and providers can
-- disagree, so DISTINCT ON collapses to one row per player-game, preferring
-- ESPN as the broader feed -- the same precedence used everywhere else.
--
-- Idempotent: only NULL rows are touched, so re-running is free.

UPDATE shot_locations s
   SET team_id = resolved.team_id
  FROM (
    SELECT DISTINCT ON (game_id, player_id)
           game_id, player_id, team_id
      FROM player_game_stats
     WHERE team_id IS NOT NULL
     ORDER BY game_id, player_id,
              CASE source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
  ) AS resolved
 WHERE resolved.game_id = s.game_id
   AND resolved.player_id = s.player_id
   AND s.team_id IS NULL;

-- The filter this column exists to serve: "every shot this team took".
CREATE INDEX IF NOT EXISTS shot_locations_team_id_idx
    ON shot_locations (team_id);
