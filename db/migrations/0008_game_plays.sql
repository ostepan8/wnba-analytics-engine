-- Play-by-play events from balldontlie (paid GOAT tier). Fixed historical
-- record for a finished game -- never revised, so upserted (not
-- append-only like market/injury snapshots) purely so a re-run is
-- idempotent rather than duplicating rows.
--
-- balldontlie's play-by-play has no structured player id: only a team and
-- a free-text description ("Rhyne Howard makes 23-foot three point jumper
-- (Te-Hina Paopao assists)"). Player attribution, if ever needed, is a
-- text-parsing problem for a consumer of this table, not something to
-- guess at during ingestion.
CREATE TABLE game_plays (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id      BIGINT NOT NULL REFERENCES games (id),
    team_id      BIGINT REFERENCES teams (id),  -- nullable: some play types may lack one
    source       TEXT NOT NULL DEFAULT 'balldontlie',

    sequence     INT NOT NULL,  -- balldontlie's "order" field; not a SQL-safe column name
    period       INT NOT NULL,
    clock        TEXT,          -- "MM:SS" countdown within the period, verbatim from source
    play_type    TEXT NOT NULL, -- e.g. "Jump Shot", "Defensive Rebound", "Jumpball"
    description  TEXT,          -- nullable: e.g. "ejection" plays carry no text (verified live)

    home_score   INT NOT NULL,
    away_score   INT NOT NULL,
    scoring_play BOOLEAN NOT NULL,
    score_value  INT NOT NULL,

    UNIQUE (game_id, sequence, source)
);

CREATE INDEX game_plays_game_idx ON game_plays (game_id);
