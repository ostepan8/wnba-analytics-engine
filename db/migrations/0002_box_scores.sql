-- Box score tables. Source is ESPN for now (sole box-score provider in this
-- repo), recorded per-row in `source` so precedence rules can be applied
-- once additional stat providers (stats.wnba.com, Phase 0 data) arrive.

CREATE TABLE team_game_stats (
    game_id             BIGINT NOT NULL REFERENCES games (id),
    team_id             BIGINT NOT NULL REFERENCES teams (id),
    source              TEXT NOT NULL,
    field_goals_made        INT NOT NULL,
    field_goals_attempted   INT NOT NULL,
    three_pointers_made     INT NOT NULL,
    three_pointers_attempted INT NOT NULL,
    free_throws_made        INT NOT NULL,
    free_throws_attempted   INT NOT NULL,
    rebounds            INT NOT NULL,
    offensive_rebounds  INT NOT NULL,
    defensive_rebounds  INT NOT NULL,
    assists             INT NOT NULL,
    steals              INT NOT NULL,
    blocks              INT NOT NULL,
    turnovers           INT NOT NULL,
    fouls               INT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, team_id, source)
);

CREATE TABLE player_game_stats (
    game_id             BIGINT NOT NULL REFERENCES games (id),
    player_id           BIGINT NOT NULL REFERENCES players (id),
    team_id             BIGINT NOT NULL REFERENCES teams (id),
    source              TEXT NOT NULL,
    starter             BOOLEAN NOT NULL DEFAULT FALSE,
    did_not_play        BOOLEAN NOT NULL DEFAULT FALSE,
    -- Stat columns are NULL for players who did not play.
    minutes             INT,
    points              INT,
    field_goals_made        INT,
    field_goals_attempted   INT,
    three_pointers_made     INT,
    three_pointers_attempted INT,
    free_throws_made        INT,
    free_throws_attempted   INT,
    rebounds            INT,
    offensive_rebounds  INT,
    defensive_rebounds  INT,
    assists             INT,
    steals              INT,
    blocks              INT,
    turnovers           INT,
    fouls               INT,
    plus_minus          INT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, player_id, source)
);

CREATE INDEX player_game_stats_player_idx ON player_game_stats (player_id);
CREATE INDEX player_game_stats_team_idx ON player_game_stats (team_id);
