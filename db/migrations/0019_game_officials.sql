-- ESPN's summary endpoint (.../summary?event=<id>) top-level `gameInfo`
-- block (see 0018_game_venue_attendance.sql for venue_name/attendance,
-- the first feature to read this block) also carries `officials`: an
-- array of the game's referee crew. Confirmed live (2026-07-09) against
-- real games spanning every WNBA era this repo backfills -- 2022 regular
-- season (event 401391705: Billy Smith, Angel Kent, Jenna Reneau), 2023
-- (401507376), 2024 (401620366-368), 2025 regular season (401736393:
-- Tiara Cruse, Paul Tuomey, Catherine Chang), 2025 preseason (401761345,
-- 401761348), and the 2025 All-Star game (401781604) -- every single one
-- sampled had exactly 3 officials, each with position.displayName
-- "Referee". Nullable role/order regardless, since a payload shape ESPN
-- hasn't sent yet (a 4-official game, a non-"Referee" role) shouldn't be
-- assumed impossible from a live sample this size.
--
-- One-to-many (a game has multiple officials), unlike venue/attendance
-- which are 1:1 scalars on games -- a dedicated table is the natural fit
-- here rather than forcing a fixed number of official_1/official_2/
-- official_3 columns onto games.
--
-- No unique constraint on (game_id, official_name): officials are fully
-- re-derivable from each summary re-fetch and persisted via a
-- delete-then-reinsert-per-game (see
-- wnba_engine/repositories/stats_repo.py::replace_game_officials), which
-- keeps idempotency simple without a multi-column upsert key.
CREATE TABLE game_officials (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         BIGINT NOT NULL REFERENCES games (id),
    official_name   TEXT NOT NULL,
    role            TEXT,
    official_order  INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX game_officials_game_id_idx ON game_officials (game_id);
