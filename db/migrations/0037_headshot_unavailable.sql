-- `has_image` was derived purely from whether a player has an ESPN crosswalk
-- id (provider_entity_map), on the assumption that having an id means the
-- headshot mirror could fetch one. It can't, for 25 of 227 such players --
-- ESPN's own resizer 404s for them, almost certainly rookies and short-stint
-- signings with no photo on file yet, which the sync job's own comment
-- already treats as a normal, expected outcome ("A provider 404 for one
-- player is normal ... It is not a failure of the sync") -- it just never
-- recorded that outcome anywhere has_image could read it back from.
--
-- This is a real, live gap: the frontend requests every has_image=true
-- player's headshot, and the browser blocks the resulting cross-origin S3
-- 404 (net::ERR_BLOCKED_BY_ORB) -- invisible to a reader (an existing
-- onError handler hides the broken <img>) but a wasted request on every
-- page load that renders one of these 25.
--
-- This migration is a one-time backfill of today's 25 known cases (each
-- checked live against the S3 bucket), not a permanent fix. It does not
-- close the gap for the future: wnba_engine/assets/images.py's sync job
-- would need to write this column itself when it hits `missing_upstream`
-- for a player, which it doesn't yet -- a newly-signed player with no
-- upstream photo will read as has_image=true again until that's done.
-- Left as a follow-up rather than rushed into this pass.

ALTER TABLE players
    ADD COLUMN IF NOT EXISTS headshot_unavailable BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE players
   SET headshot_unavailable = TRUE
 WHERE id IN (
    558, 511, 254, 556, 260, 554, 551, 266, 533, 339, 564, 69, 280, 209,
    563, 1005, 264, 298, 300, 565, 566, 305, 335, 309, 549
 );
