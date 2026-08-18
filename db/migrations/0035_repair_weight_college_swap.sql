-- Repair players whose `college` came back empty from the source and whose
-- `weight` holds a college name instead. Found by an audit pass, then
-- independently re-checked here rather than trusted: the audit's own list
-- named 23 players, but the general predicate below (a weight value that
-- doesn't start with a digit -- no real weight does) catches 25, correctly
-- picking up two the audit missed (Janiah Barker/Tennessee, Kara Dunn/USC)
-- while still excluding two legitimate weights recorded with a unit suffix
-- ("181 lbs", "154 lbs") that a naive non-numeric check would have wrongly
-- swept in.
--
-- This is a source-payload issue, not a bug in this codebase's own parsing:
-- wnba_engine/balldontlie/player_ref_parsing.py reads weight and college as
-- two fully independent fields with no positional/offset logic that could
-- swap them locally. No validation anywhere in wnba_engine/validation/
-- currently flags a non-numeric weight, which is why this went unnoticed --
-- a future ingest pass repeating the upstream mistake will need a real check
-- to catch it again; this migration only repairs what is already stored.

UPDATE players
   SET college = weight,
       weight = NULL
 WHERE college IS NULL
   AND weight IS NOT NULL
   AND weight !~ '^[0-9]';
