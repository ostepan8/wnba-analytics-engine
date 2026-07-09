-- Append-only standings *history*: a timestamped snapshot on every
-- ingestion run, alongside (not instead of) the CURRENT-STATE
-- team_standings upsert table from db/migrations/0013_standings.sql.
--
-- 0013 explicitly scoped standings-over-time out: "Tracking
-- standings-over-time (e.g. a daily snapshot history) would be a separate,
-- bigger feature and is explicitly out of scope here." This migration is
-- that feature. team_standings is upserted on (team_id, season, source)
-- specifically because downstream consumers want "give me the standings
-- right now" -- fast, one row per team, no scan/aggregation needed. This
-- table exists for the complementary need: "show me the wins/losses trend
-- over the season", which an upsert-only table can never answer since
-- every re-fetch overwrites the prior values. Same rationale as
-- market_price_snapshots (0003_market_price_snapshots.sql): "we want price
-- *history*, not just the latest quote."
--
-- Both tables are written together, in the same ingestion run and the same
-- transaction (see balldontlie_standings_ingest.backfill_season) -- one
-- balldontlie /wnba/v1/standings fetch upserts team_standings AND appends
-- a row here. Same columns as team_standings, plus captured_at to mark
-- when this snapshot was taken. No UNIQUE constraint: this table is
-- deliberately append-only, never upserted.
CREATE TABLE team_standings_history (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_id              BIGINT NOT NULL REFERENCES teams (id),
    season               INT NOT NULL,
    source               TEXT NOT NULL DEFAULT 'balldontlie',

    conference           TEXT NOT NULL,
    wins                 INT NOT NULL,
    losses               INT NOT NULL,
    win_percentage       NUMERIC NOT NULL,
    games_behind         NUMERIC NOT NULL,
    home_record          TEXT NOT NULL,
    away_record          TEXT NOT NULL,
    conference_record    TEXT NOT NULL,
    playoff_seed         INT NOT NULL,

    captured_at          TIMESTAMPTZ NOT NULL
);

CREATE INDEX team_standings_history_team_season_idx
    ON team_standings_history (team_id, season, source, captured_at);
CREATE INDEX team_standings_history_captured_at_idx
    ON team_standings_history (captured_at);
