-- Player attribution on plays, and shot locations, from stats.wnba.com.
--
-- FEATURE_ROADMAP.md ss9 lists player-level play-by-play as **blocked** --
-- "no player id on plays, names are free text only". That was true of
-- balldontlie, the only play source until now. The league's own stats API
-- carries PLAYER1_ID / PLAYER2_ID / PLAYER3_ID on 97% of events and goes
-- back to 1997, so the block is a property of the provider we happened to
-- use rather than of the sport.
--
-- Plays land in the EXISTING game_plays table under a new `source`, not a
-- new table. That is what the source column and
-- UNIQUE(game_id, sequence, source) were built for -- the same pattern
-- player_game_stats already uses to hold espn and balldontlie side by
-- side -- and it means every existing query keeps working untouched while
-- a caller who wants attribution filters to source='wnba_stats'.
--
-- THE THREE PLAYER COLUMNS ARE NOT INTERCHANGEABLE. The league feed uses
-- slot 1 for the actor, slot 2 for the secondary participant (the assister
-- on a make, the shooter on a block) and slot 3 for a third party (the
-- stealer's victim). Collapsing them to one "player_id" would lose exactly
-- the relational information that makes this source worth adding.

ALTER TABLE game_plays ADD COLUMN player1_id BIGINT REFERENCES players (id);
ALTER TABLE game_plays ADD COLUMN player2_id BIGINT REFERENCES players (id);
ALTER TABLE game_plays ADD COLUMN player3_id BIGINT REFERENCES players (id);
ALTER TABLE game_plays ADD COLUMN event_type INTEGER;
ALTER TABLE game_plays ADD COLUMN event_action_type INTEGER;

CREATE INDEX game_plays_player1_idx ON game_plays (player1_id)
    WHERE player1_id IS NOT NULL;

-- Shot locations. player_shot_zone_stats holds SEASON aggregates in eight
-- buckets; this is one row per attempt with court coordinates, which is a
-- different question -- shot quality and shot selection rather than a
-- season profile.
--
-- LOC_X / LOC_Y are in tenths of a foot from the basket, x positive to the
-- right of the hoop looking at the offensive basket. Stored raw rather
-- than converted: the provider's units are the thing that is documented,
-- and a derived distance already arrives in shot_distance.
CREATE TABLE shot_locations (
    id                BIGSERIAL PRIMARY KEY,
    game_id           BIGINT NOT NULL REFERENCES games (id),
    player_id         BIGINT REFERENCES players (id),
    team_id           BIGINT REFERENCES teams (id),
    source            TEXT NOT NULL,
    -- The play this shot corresponds to, so a shot can be joined back to
    -- its play-by-play context (who assisted, the score at the time).
    game_event_id     INTEGER NOT NULL,
    period            INTEGER,
    seconds_remaining INTEGER,
    action_type       TEXT,
    shot_type         TEXT,
    shot_zone_basic   TEXT,
    shot_zone_area    TEXT,
    shot_zone_range   TEXT,
    shot_distance     INTEGER,
    loc_x             INTEGER,
    loc_y             INTEGER,
    made              BOOLEAN NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One shot is one (game, event) per source. Not keyed on player: a
    -- game_event_id is unique within its game regardless of who took it,
    -- and including the player would let a mis-resolved name double a row.
    CONSTRAINT shot_locations_event_key UNIQUE (game_id, game_event_id, source)
);

CREATE INDEX shot_locations_player_idx ON shot_locations (player_id, game_id);
CREATE INDEX shot_locations_game_idx ON shot_locations (game_id);
