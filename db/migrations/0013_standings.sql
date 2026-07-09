-- Official league standings from balldontlie (paid GOAT tier):
-- /wnba/v1/standings, verified live -- a single flat response (no
-- "meta"/pagination wrapper), one row per team per season (~13 rows for
-- the whole league, confirmed against season=2025).
--
-- This is a CURRENT-STATE snapshot, not a time series: re-fetching gives
-- the standings as of right now (wins/losses/games_behind keep changing
-- all season), so rows are upserted on (team_id, season, source) exactly
-- like player_advanced_stats/team_advanced_stats -- never append-only.
-- Tracking standings-over-time (e.g. a daily snapshot history) would be a
-- separate, bigger feature and is explicitly out of scope here.
--
-- Every field from the live payload is promoted to a typed column: unlike
-- the per-game advanced-stats payloads, there's no large "misc"/"usage"
-- JSONB category here worth keeping verbatim -- standings are inherently
-- small and every field (wins, losses, games_behind, home/away/conference
-- records, playoff_seed) is worth querying/indexing on directly.
-- home_record/away_record/conference_record are free-text "W-L" strings
-- (e.g. "16-6"), not split win/loss columns -- verified live.
CREATE TABLE team_standings (
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

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (team_id, season, source)
);

CREATE INDEX team_standings_season_idx ON team_standings (season);
