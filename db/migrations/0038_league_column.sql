-- NBA expansion (NBA_EXPANSION.md, Option A): this project's canonical-
-- identity design (teams/games/players + provider_entity_map) was built
-- assuming a single league. Nothing stopped "Washington" or "GS" from
-- meaning two different real-world teams, because there was only ever one
-- league to disambiguate. This adds an explicit `league` column to all
-- three canonical tables so every lookup, matcher, and aggregate can be
-- scoped to one league, while keeping one queryable dataset across both.
--
-- DEFAULT 'wnba' backfills every existing row in the same statement
-- (metadata-only default fill, same idiom as 0037_headshot_unavailable.sql)
-- -- every row in this database today is WNBA data.
--
-- provider_entity_map is deliberately NOT touched here: ESPN, Kalshi, and
-- Polymarket external ids are already globally unique across leagues
-- (Kalshi/Polymarket tickers embed the league in the ticker/slug itself;
-- ESPN ids are unique per the site API as a whole). A second stats.nba.com
-- provider is onboarded under its own provider string (`nba_stats`, not
-- `wnba_stats`) specifically so its numeric team/player/game ids never
-- share a crosswalk row with stats.wnba.com's, without needing a schema
-- change here.

ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'wnba'
        CHECK (league IN ('wnba', 'nba'));

ALTER TABLE players
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'wnba'
        CHECK (league IN ('wnba', 'nba'));

ALTER TABLE games
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'wnba'
        CHECK (league IN ('wnba', 'nba'));

-- Abbreviations and names are only unique WITHIN a league now (e.g. "GS"
-- could exist in both). Existing lookups that assumed global uniqueness
-- must add `AND league = %(league)s`; these indexes make that scoped
-- lookup cheap instead of introducing a new full-table-scan cost.
CREATE INDEX IF NOT EXISTS teams_league_idx ON teams (league);
CREATE INDEX IF NOT EXISTS players_league_idx ON players (league);

-- Replaces games_season_idx: every season query in this codebase is now
-- also league-scoped, so the composite index serves both the old
-- single-column pattern and the new league-scoped one.
DROP INDEX IF EXISTS games_season_idx;
CREATE INDEX IF NOT EXISTS games_league_season_idx ON games (league, season);
