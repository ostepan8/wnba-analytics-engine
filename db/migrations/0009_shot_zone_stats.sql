-- Season-level shot-zone efficiency splits from balldontlie (paid GOAT
-- tier). Despite balldontlie's endpoint name ("shot_locations"), this is
-- NOT per-shot x/y coordinate data -- balldontlie doesn't expose spatial
-- shot charts. It's field goal attempts/makes aggregated into 8 fixed
-- court zones, one row per player (or team) per season. The 8-zone
-- taxonomy is stable and well-known, so promoted to real columns rather
-- than kept as JSONB (same rationale as 0006's "advanced"/"four_factors"
-- promotion) -- fg_pct is not stored since it's a trivial fga/fgm ratio.
CREATE TABLE player_shot_zone_stats (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id                BIGINT NOT NULL REFERENCES players (id),
    team_id                  BIGINT REFERENCES teams (id),
    season                   INT NOT NULL,
    season_type              TEXT NOT NULL,  -- e.g. 'regular', 'playoffs'
    source                   TEXT NOT NULL DEFAULT 'balldontlie',

    restricted_area_fga      INT,
    restricted_area_fgm      INT,
    in_the_paint_non_ra_fga  INT,
    in_the_paint_non_ra_fgm  INT,
    mid_range_fga            INT,
    mid_range_fgm            INT,
    left_corner_3_fga        INT,
    left_corner_3_fgm        INT,
    right_corner_3_fga       INT,
    right_corner_3_fgm       INT,
    corner_3_fga             INT,
    corner_3_fgm             INT,
    above_the_break_3_fga    INT,
    above_the_break_3_fgm    INT,
    backcourt_fga            INT,
    backcourt_fgm            INT,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (player_id, season, season_type, source)
);

CREATE INDEX player_shot_zone_stats_player_idx ON player_shot_zone_stats (player_id);

CREATE TABLE team_shot_zone_stats (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_id                  BIGINT NOT NULL REFERENCES teams (id),
    season                   INT NOT NULL,
    season_type              TEXT NOT NULL,
    source                   TEXT NOT NULL DEFAULT 'balldontlie',

    restricted_area_fga      INT,
    restricted_area_fgm      INT,
    in_the_paint_non_ra_fga  INT,
    in_the_paint_non_ra_fgm  INT,
    mid_range_fga            INT,
    mid_range_fgm            INT,
    left_corner_3_fga        INT,
    left_corner_3_fgm        INT,
    right_corner_3_fga       INT,
    right_corner_3_fgm       INT,
    corner_3_fga             INT,
    corner_3_fgm             INT,
    above_the_break_3_fga    INT,
    above_the_break_3_fgm    INT,
    backcourt_fga            INT,
    backcourt_fgm            INT,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (team_id, season, season_type, source)
);

CREATE INDEX team_shot_zone_stats_team_idx ON team_shot_zone_stats (team_id);
