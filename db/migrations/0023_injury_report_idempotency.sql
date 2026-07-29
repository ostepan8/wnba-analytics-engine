-- Make injury_reports re-ingestible, for the same reason 0022 did it for
-- market_price_snapshots.
--
-- ESPN's /injuries endpoint is current-state-only -- there is no
-- historical version (see 0005_injury_reports.sql), so a day not recorded
-- is a day permanently lost. The Wayback backfill recovers only what
-- archive.org happened to crawl, which across three months of the 2026
-- season was 11 days. That makes this feed belong on the always-on
-- capture host alongside the market feeds (see wnba_engine/market_capture/),
-- and capture means replay.
--
-- Nothing prevented the same observation being appended twice: 0005
-- created only btree indexes. Every replay would have duplicated the
-- report.
--
-- (source, player_id, captured_at) is the natural key: one source's view
-- of one player, observed at one instant, is one fact. Verified against
-- the live database before adding -- 24,073 rows, zero violations, and
-- player_id is NOT NULL so there are no NULL-distinctness surprises.
--
-- Deliberately NOT (source, player_id, reported_at): reported_at is when
-- the INJURY was reported, not when we observed it, so the same injury
-- legitimately recurs across every daily snapshot until it resolves.
-- That key has 20,971 real duplicates and would destroy the history this
-- table exists to keep.

ALTER TABLE injury_reports
    ADD CONSTRAINT injury_reports_source_player_captured_key
    UNIQUE (source, player_id, captured_at);
