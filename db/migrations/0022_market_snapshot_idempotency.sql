-- Make market_price_snapshots re-ingestible.
--
-- The table has always been append-only, but nothing enforced that the
-- SAME observation couldn't be appended twice: 0003 created only a plain
-- btree on (provider, market_external_id, captured_at), not a unique one.
-- That was fine while the only writer was a live snapshot job whose
-- captured_at was wall-clock and therefore never repeated.
--
-- It stops being fine now that captures are recorded as raw provider
-- payloads on a separate always-on machine and replayed here (see
-- wnba_engine/market_capture/). Replay is the whole point of that
-- design -- re-run a file after a parser improves, re-sync a directory
-- without tracking exactly which files were already loaded -- and every
-- one of those re-runs would previously have silently doubled the
-- rows.
--
-- (provider, market_external_id, captured_at) is the natural key: one
-- provider's one market, observed at one instant, is one fact. Verified
-- against the live database before adding -- 63,599 existing rows, zero
-- violations -- so this constrains what was already true rather than
-- changing the data.
--
-- Same UNIQUE(...external_id, captured_at) idempotency convention as
-- sportsbook_game_odds (0014) and odds_api_game_scores (0021). Inserts
-- use ON CONFLICT DO NOTHING, so a duplicate observation is a no-op, not
-- an error -- a re-ingested file reports 0 inserted rather than failing.
--
-- The existing non-unique index is dropped: the unique constraint's own
-- index serves the same (provider, market_external_id, captured_at)
-- lookups, so keeping both would just cost writes and disk.

ALTER TABLE market_price_snapshots
    ADD CONSTRAINT market_price_snapshots_provider_market_captured_key
    UNIQUE (provider, market_external_id, captured_at);

DROP INDEX IF EXISTS market_price_snapshots_market_time_idx;
