-- Append-only injury report snapshots, same pattern as market_price_snapshots.
--
-- ESPN's injuries feed (site.api.espn.com/.../injuries) is CURRENT-STATE
-- ONLY: querying it against a years-old game still returns today's live
-- report, not a historical one (verified directly -- a 2022 game's
-- "injuries" showed 2026 players). There is no historical injury data to
-- backfill; this table only ever gains real history from the moment we
-- start capturing, going forward. Every capture inserts fresh rows so we
-- build genuine point-in-time history rather than overwriting state.
CREATE TABLE injury_reports (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    espn_injury_id   TEXT NOT NULL,
    player_id        BIGINT NOT NULL REFERENCES players (id),
    team_id          BIGINT NOT NULL REFERENCES teams (id),
    status           TEXT NOT NULL,        -- ESPN's status label, e.g. "Out", "Questionable"
    status_type      TEXT NOT NULL,        -- ESPN's stable type code, e.g. "INJURY_STATUS_OUT"
    injury_type      TEXT,                 -- e.g. "Knee", "Ankle"
    side             TEXT,                 -- e.g. "Left", "Right"
    return_date      DATE,
    short_comment    TEXT,
    long_comment     TEXT,
    reported_at      TIMESTAMPTZ NOT NULL, -- ESPN's own "date" field on the injury note
    captured_at      TIMESTAMPTZ NOT NULL, -- when our sweep pulled this
    source           TEXT NOT NULL DEFAULT 'espn',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX injury_reports_player_idx ON injury_reports (player_id, captured_at DESC);
CREATE INDEX injury_reports_captured_at_idx ON injury_reports (captured_at);
