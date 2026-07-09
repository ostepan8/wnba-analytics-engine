-- Ground-truth WNBA season award winners (MVP, ROY, DPOY, Sixth Player of
-- the Year, Coach of the Year, Most Improved Player, Finals MVP, All-WNBA
-- First/Second Team, All-Defensive First/Second Team, All-Rookie Team),
-- hand-researched from Wikipedia/WNBA.com/basketball-reference -- see
-- wnba_engine/pipeline/season_awards_seed.py for the actual data and
-- source citations, and why this is a one-off seed script rather than a
-- live-API pipeline (no API for historical award winners exists).
--
-- Used as ground truth to verify Kalshi/Polymarket season-award
-- prediction markets against real outcomes.
--
-- Coach of the Year is the one award here that names a COACH, not a
-- player -- we have no `coaches` table, so the coach's name lives in
-- raw_name (same as every other award) and team_id links to the team
-- they coached that season, since a coach has no players.id row to
-- attach to.
--
-- team_selection distinguishes the two split-team awards (All-WNBA,
-- All-Defensive: 'first'/'second', 5 rows each = 10 per season) from
-- single-winner awards and All-Rookie (a single unified team, not split),
-- which get the 'na' sentinel default rather than NULL -- a multi-column
-- UNIQUE index treats every NULL as distinct from every other NULL in
-- Postgres, so two same-season/award/raw_name rows with team_selection
-- NULL would NOT collide and the dedup index would silently allow
-- duplicates. A NOT NULL sentinel sidesteps that entirely instead of
-- reaching for a partial/expression index.
CREATE TABLE season_awards (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season         INT NOT NULL,
    award          TEXT NOT NULL,  -- 'mvp' | 'roy' | 'dpoy' | 'sixth_poy' | 'coy' |
                                    -- 'mip' | 'finals_mvp' | 'all_wnba' | 'all_defense' | 'all_rookie'
    team_selection TEXT NOT NULL DEFAULT 'na',  -- 'first' | 'second' | 'na'
    player_id      BIGINT REFERENCES players (id),  -- NULL if raw_name never resolved
    -- The name as researched, ALWAYS populated (even when player_id
    -- resolves) so the ground-truth text survives regardless of
    -- resolution; for 'coy' this is the coach's name, not a player.
    raw_name       TEXT NOT NULL,
    team_id        BIGINT REFERENCES teams (id),  -- coach's team for coy; optional elsewhere
    source         TEXT NOT NULL,  -- URL(s) verified against, semicolon-separated when 2+
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotency: a second seed run must not duplicate rows. See seed script
-- module docstring for the ON CONFLICT DO NOTHING this backs.
CREATE UNIQUE INDEX season_awards_dedup_idx
    ON season_awards (season, award, team_selection, raw_name);

CREATE INDEX season_awards_season_award_idx ON season_awards (season, award);
CREATE INDEX season_awards_player_idx ON season_awards (player_id);
