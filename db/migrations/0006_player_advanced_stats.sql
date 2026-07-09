-- Advanced per-player-per-game stats from balldontlie (paid GOAT tier;
-- ESPN and stats.wnba.com don't expose this -- stats.wnba.com is real but
-- fights bot detection aggressively (Akamai silently drops connections),
-- and balldontlie already does that work reliably behind a normal API key).
--
-- The "advanced" and "four_factors" categories (offensive/defensive rating,
-- pace, true shooting%, usage%, PIE, etc.) are promoted to real columns
-- since they're the fields actually worth querying/indexing on. "misc",
-- "usage" (the detailed percentage-of-team-total breakdowns), and
-- "scoring" categories are kept as JSONB -- real data, just not worth ~40
-- more dedicated columns for splits unlikely to be queried directly.
CREATE TABLE player_advanced_stats (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id                         BIGINT NOT NULL REFERENCES games (id),
    player_id                      BIGINT NOT NULL REFERENCES players (id),
    team_id                        BIGINT NOT NULL REFERENCES teams (id),
    source                         TEXT NOT NULL DEFAULT 'balldontlie',

    minutes                        TEXT,  -- "MM:SS", same free-text shape as ESPN's box score

    -- "advanced" category
    offensive_rating                NUMERIC,
    defensive_rating                NUMERIC,
    net_rating                      NUMERIC,
    pace                            NUMERIC,
    possessions                     INT,
    true_shooting_percentage        NUMERIC,
    effective_field_goal_percentage NUMERIC,
    usage_percentage                NUMERIC,
    assist_percentage               NUMERIC,
    assist_ratio                    NUMERIC,
    assist_to_turnover              NUMERIC,
    turnover_ratio                  NUMERIC,
    rebound_percentage              NUMERIC,
    offensive_rebound_percentage    NUMERIC,
    defensive_rebound_percentage    NUMERIC,
    pie                             NUMERIC,  -- Player Impact Estimate

    -- "four_factors" category (fields not already covered above)
    free_throw_attempt_rate         NUMERIC,
    team_turnover_percentage        NUMERIC,
    opp_effective_field_goal_percentage NUMERIC,
    opp_free_throw_attempt_rate     NUMERIC,
    opp_team_turnover_percentage    NUMERIC,
    opp_offensive_rebound_percentage NUMERIC,

    -- "misc", "usage", "scoring" categories, verbatim
    misc_stats                      JSONB,
    usage_stats                     JSONB,
    scoring_stats                   JSONB,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (game_id, player_id, source)
);

CREATE INDEX player_advanced_stats_player_idx ON player_advanced_stats (player_id);
CREATE INDEX player_advanced_stats_team_idx ON player_advanced_stats (team_id);
