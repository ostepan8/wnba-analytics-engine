-- Canonical entity tables: our own ID space for teams, players, and games.
-- These are deliberately NOT shaped after any single provider's response;
-- every provider's external IDs resolve to these rows through
-- provider_entity_map (the crosswalk), so onboarding a new source never
-- requires new bespoke ID columns here.

CREATE TABLE teams (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    abbreviation TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- No unique constraint on players.name: two players can share a name.
-- Cross-provider dedup happens exclusively via provider_entity_map; a new
-- provider's players must be mapped (automatically or manually) before its
-- rows merge with existing canonical players.
CREATE TABLE players (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name   TEXT NOT NULL,
    position    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE games (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season        INT NOT NULL,
    start_time    TIMESTAMPTZ NOT NULL,
    home_team_id  BIGINT NOT NULL REFERENCES teams (id),
    away_team_id  BIGINT NOT NULL REFERENCES teams (id),
    status        TEXT NOT NULL,
    -- Scores here come from ESPN, currently the sole score source in this
    -- repo. Phase 0 (the private the-odds-api pipeline) already has final
    -- scores and, per ROADMAP.md, wins over ESPN when it is folded in —
    -- at that point a source/precedence column (or a scores-by-source
    -- table) resolves conflicts. Documented now so the future rule is not
    -- a surprise.
    home_score    INT,
    away_score    INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX games_start_time_idx ON games (start_time);
CREATE INDEX games_season_idx ON games (season);

-- Crosswalk: (provider, entity_type, external_id) -> canonical internal id.
-- One table covers every provider and entity type (ESPN team/player/game
-- ids, Kalshi event tickers, Polymarket event ids, ...) so adding a
-- provider never means adding a table.
CREATE TABLE provider_entity_map (
    provider     TEXT NOT NULL,
    entity_type  TEXT NOT NULL,  -- 'team' | 'player' | 'game'
    external_id  TEXT NOT NULL,
    internal_id  BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, entity_type, external_id)
);

CREATE INDEX provider_entity_map_internal_idx
    ON provider_entity_map (entity_type, internal_id);
