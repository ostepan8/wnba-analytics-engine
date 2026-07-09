-- Append-only injury snapshots from balldontlie's /wnba/v1/player_injuries
-- endpoint -- current-state only, same philosophy as ESPN's injury_reports
-- (see 0005_injury_reports.sql), but NOT folded into that table: balldontlie's
-- shape is genuinely thinner and free-text where ESPN's is structured
-- (verified live). A single free-text `status` (e.g. "Out", "Day-To-Day")
-- has no stable type code the way ESPN's status_type
-- (e.g. "INJURY_STATUS_OUT") does, there are no injury_type/side fields at
-- all, a single `comment` field stands in for ESPN's short/long comment
-- split, and `return_date` is a bare "Mon D" string with no year (e.g.
-- "Jul 9") rather than an ISO date. Reusing injury_reports would mean
-- inventing values for its NOT NULL status_type column and guessing at
-- return_date's ambiguous year -- so this is a second live source for
-- cross-validation against ESPN's report, same rationale as balldontlie's
-- box-score tables, but (unlike box scores, whose balldontlie rows slot
-- into ESPN's exact same columns -- see 0002_box_scores.sql) a distinct
-- table because the column shapes genuinely don't match.
CREATE TABLE balldontlie_injury_reports (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id        BIGINT NOT NULL REFERENCES players (id),
    team_id          BIGINT NOT NULL REFERENCES teams (id),
    status           TEXT NOT NULL,        -- balldontlie's free-text status, e.g. "Out"
    return_date_text TEXT,                 -- raw "Mon D" string, no year (e.g. "Jul 9")
    comment          TEXT,                 -- balldontlie's single free-text note
    captured_at      TIMESTAMPTZ NOT NULL, -- when our sweep pulled this
    source           TEXT NOT NULL DEFAULT 'balldontlie',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX balldontlie_injury_reports_player_idx
    ON balldontlie_injury_reports (player_id, captured_at DESC);
CREATE INDEX balldontlie_injury_reports_captured_at_idx
    ON balldontlie_injury_reports (captured_at);
