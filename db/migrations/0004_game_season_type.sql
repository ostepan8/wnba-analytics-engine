-- ESPN's scoreboard distinguishes preseason/regular-season/post-season
-- (season.type), which this table never captured. Without it, a preseason
-- win is indistinguishable from a real one -- caught via a standings
-- mismatch: 2026 Minnesota showed 18-6 here vs. the real 15-6 record,
-- because 3 preseason wins were counted as regular-season wins.
--
-- Nullable: existing rows are unknown until the next ESPN sync/backfill
-- re-populates them (upsert_game always sets this field going forward).
ALTER TABLE games ADD COLUMN season_type TEXT;
