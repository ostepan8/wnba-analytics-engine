-- Merge two never-linked identities for the same real player: Kayla
-- Alexander, Toronto Tempo, appears as internal player 872 (from balldontlie,
-- provider_entity_map external_id 337) and separately as internal player
-- 1005 (from ESPN external_id 2491232 and wnba_stats external_id 203405).
-- Neither name-matching pass that would normally catch this ever ran them
-- together into one identity -- exactly the provider_entity_map resolution
-- gap AGENTS.md's "canonical identity" section describes, found live: her
-- box score totals for the same 5 games were split across two player ids,
-- and the roster page showed her twice.
--
-- 1005 is kept as the surviving id: it already resolves through two
-- providers (espn, wnba_stats) against 872's one (balldontlie), and keeping
-- it moves less data overall (872 has 11 FK rows across three tables; 1005
-- has 66 across game_plays/shot_locations/player_transactions/
-- player_game_stats that would otherwise need moving the other way).
--
-- player_game_stats is the one table where BOTH ids carry rows for the same
-- games -- checked first, not assumed: all of 872's rows are source
-- 'balldontlie' and all of 1005's are source 'espn', for the identical five
-- game ids, so re-pointing 872's rows at 1005 cannot collide with the
-- primary key (game_id, player_id, source) -- it simply adds a second
-- source's readings the way any other player's multi-provider row already
-- works, no different code path needed to read it correctly afterward.
--
-- Bio fields on 872 (jersey_number, height, age, and college -- corrected by
-- migration 0035, since 872 was also one of the weight/college-swapped
-- rows) are real data 1005 never had; carried forward rather than dropped.

BEGIN;

-- 1. Re-point every FK reference at the surviving id. Checked beforehand
--    (not assumed) that only player_game_stats has rows under both ids, and
--    that its natural key can't collide -- see comment above.
UPDATE balldontlie_injury_reports SET player_id = 1005 WHERE player_id = 872;
UPDATE injury_reports             SET player_id = 1005 WHERE player_id = 872;
UPDATE market_price_snapshots     SET player_id = 1005 WHERE player_id = 872;
UPDATE player_advanced_stats      SET player_id = 1005 WHERE player_id = 872;
UPDATE player_game_stats          SET player_id = 1005 WHERE player_id = 872;
UPDATE player_name_resolutions    SET player_id = 1005 WHERE player_id = 872;
UPDATE player_shot_zone_stats     SET player_id = 1005 WHERE player_id = 872;
UPDATE player_transactions        SET player_id = 1005 WHERE player_id = 872;
UPDATE season_awards               SET player_id = 1005 WHERE player_id = 872;
UPDATE shot_locations              SET player_id = 1005 WHERE player_id = 872;
UPDATE sportsbook_player_prop_odds SET player_id = 1005 WHERE player_id = 872;
UPDATE game_plays SET player1_id = 1005 WHERE player1_id = 872;
UPDATE game_plays SET player2_id = 1005 WHERE player2_id = 872;
UPDATE game_plays SET player3_id = 1005 WHERE player3_id = 872;

-- 2. Re-point 872's provider mapping at the surviving id, so future
--    balldontlie ingests resolve straight to 1005 instead of recreating 872.
UPDATE provider_entity_map
   SET internal_id = 1005
 WHERE entity_type = 'player'
   AND internal_id = 872;

-- 3. Carry forward the bio data 1005 never had. Position is left as 1005's
--    own 'C' (already the correct abbreviated form; 872's was the
--    unabbreviated 'Center' from its source, not worth preferring).
UPDATE players dst
   SET jersey_number = coalesce(dst.jersey_number, src.jersey_number),
       height         = coalesce(dst.height, src.height),
       age            = coalesce(dst.age, src.age),
       college        = coalesce(dst.college, src.college)
  FROM players src
 WHERE dst.id = 1005
   AND src.id = 872;

-- 4. The old identity is now referenced by nothing and carries no
--    information the surviving row doesn't already have.
DELETE FROM players WHERE id = 872;

COMMIT;
