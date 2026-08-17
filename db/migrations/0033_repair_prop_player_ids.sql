-- Repair player_id on prediction-market player props.
--
-- The Kalshi ingest cached its player lookup per EVENT and applied the result
-- to every market under it. An event holds many players' props and the player
-- is named in each market's TITLE, so the first market's player was stamped
-- onto all the rest: 76,776 of 179,882 rows carried the wrong player, with one
-- id standing in for a dozen people. Sonia Citron's id appeared on props for
-- Kahleah Copper, Angel Reese, Cameron Brink and others.
--
-- Fixed at the source in wnba_engine/pipeline/kalshi_ingest.py, which now keys
-- the cache on (event, title). This repairs what is already stored.
--
-- The name is recoverable because it is the text before the colon in `outcome`
-- -- "Rhyne Howard: 15+" and "Aliyah Boston: Assists O/U 3.5" alike. Rows are
-- re-pointed at the player that name actually resolves to.
--
-- Matching here is on players.full_name only. The engine's alias handling lives
-- in Python (wnba_engine/player_aliases.py), not in a table this migration can
-- join to, so a name that needs an alias is set to NULL and left for the next
-- ingest -- which does apply aliases -- to map correctly.
--
-- A row whose name resolves to nobody is set to NULL rather than left pointing
-- at the wrong person. An unmapped prop is merely unusable; a mis-mapped one is
-- a wrong answer presented with confidence.

-- 1. Re-point every prop row at the player its own outcome names.
UPDATE market_price_snapshots m
   SET player_id = resolved.player_id
  FROM (
    SELECT s.id, p.id AS player_id
      FROM market_price_snapshots s
      JOIN players p
        ON lower(p.full_name) = lower(trim(split_part(s.outcome, ':', 1)))
     WHERE s.outcome LIKE '%:%'
  ) AS resolved
 WHERE m.id = resolved.id
   AND m.player_id IS DISTINCT FROM resolved.player_id;

-- 2. Anything still pointing at a player whose name does not match its own
--    outcome is a leftover from the old grouping. NULL beats wrong.
UPDATE market_price_snapshots m
   SET player_id = NULL
  FROM players p
 WHERE m.player_id = p.id
   AND m.outcome LIKE '%:%'
   AND lower(p.full_name) IS DISTINCT FROM lower(trim(split_part(m.outcome, ':', 1)));

-- Props are read per player; without this every such query is a full scan of a
-- 1.4-million-row table.
CREATE INDEX IF NOT EXISTS market_price_snapshots_player_id_idx
    ON market_price_snapshots (player_id)
 WHERE player_id IS NOT NULL;
