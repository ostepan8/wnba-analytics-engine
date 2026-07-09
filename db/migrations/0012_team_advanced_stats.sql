-- Advanced per-team-per-game stats from balldontlie (paid GOAT tier), mirroring
-- player_advanced_stats (see 0006_player_advanced_stats.sql) at team-game
-- granularity: /wnba/v1/team_game_advanced_stats returns the same
-- misc/usage/scoring/advanced/four_factors category shape as the
-- player-level endpoint (verified live), just with no player dimension.
--
-- Same promotion judgment as player_advanced_stats: "advanced" and
-- "four_factors" fields worth querying/indexing on become real columns;
-- "misc", "usage", "scoring" stay JSONB. The team-level "advanced" category
-- also carries one extra live field (estimated_team_turnover_percentage)
-- not present on the player-level payload -- intentionally not promoted,
-- for the same reason the other "estimated_*" siblings aren't (kept the
-- promoted-column set identical across both tables).
CREATE TABLE team_advanced_stats (
    id                              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id                         BIGINT NOT NULL REFERENCES games (id),
    team_id                        BIGINT NOT NULL REFERENCES teams (id),
    source                         TEXT NOT NULL DEFAULT 'balldontlie',

    minutes                        TEXT,  -- "MM:SS", same free-text shape as player_advanced_stats

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
    pie                             NUMERIC,  -- Player Impact Estimate (team-level here)

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

    UNIQUE (game_id, team_id, source)
);

CREATE INDEX team_advanced_stats_team_idx ON team_advanced_stats (team_id);
