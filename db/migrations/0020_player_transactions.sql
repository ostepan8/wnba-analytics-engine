-- ESPN's transactions endpoint (.../transactions?season=YYYY&limit=200) --
-- roster moves (signings, waivers, releases, trades, activations, front
-- office/coaching hires, etc). A genuinely different concept from every
-- other ESPN feed this repo ingests: there is no structured player field
-- at all. Each entry is `{date, description, team}` where `description` is
-- free text like "Waived F Liatu King." or "Released F Joyner Holmes and
-- G Jazmine Jones." -- sometimes two distinct actions in one string, and
-- occasionally missing a player entirely (coaching/front-office moves:
-- "Named Clare Duwelius general manager.", "Hired Stephanie White as head
-- coach.") or carrying a source data-quality defect ESPN itself has (e.g.
-- "Gs Marina Mabrey and DeWanna signed a contract amendment..." -- "DeWanna"
-- has no last name in ESPN's own text).
--
-- Design: `description` is ALWAYS stored verbatim, in full -- nothing is
-- ever lost, even when best-effort parsing below fails completely. Ground
-- truth lives in that column, not in the derived columns. `transaction_date`
-- and `team_id`/`raw_team_name` are reliable and structured (ESPN always
-- sends these). `transaction_type` and `player_id`/`raw_player_name` are
-- BEST-EFFORT extraction off the free text (see
-- wnba_engine/espn/transaction_classifier.py) -- transaction_type falls
-- back to 'other' when unclassified; player_id/raw_player_name are both
-- NULL when no player can be confidently isolated (a coaching/front-office
-- move, or text the extractor can't parse). A description naming two
-- players or two distinct actions only ever yields ONE type and ONE player
-- here -- documented, accepted limitation of parsing free text, not a bug.
--
-- team_id is nullable (not NOT NULL like most FK columns in this repo):
-- unlike team_standings/team_advanced_stats, which only ever see teams this
-- repo already knows from scoreboard ingestion, a lookup miss here must not
-- drop the whole transaction -- raw_team_name preserves the source value
-- regardless of whether the crosswalk resolves.
--
-- Append-only, same idiom as team_standings_history
-- (0015_standings_history.sql): ESPN gives no transaction id to upsert
-- against, and every entry is itself an immutable historical fact (a
-- signing that already happened doesn't get "updated" later). Idempotent
-- re-runs rely on the UNIQUE constraint below + ON CONFLICT DO NOTHING
-- instead of an upsert key.
CREATE TABLE player_transactions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_date    TIMESTAMPTZ NOT NULL,
    team_id             BIGINT REFERENCES teams (id),
    raw_team_name       TEXT NOT NULL,
    player_id           BIGINT REFERENCES players (id),
    raw_player_name     TEXT,
    transaction_type    TEXT NOT NULL,
    description         TEXT NOT NULL,
    source              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Natural dedup key: ESPN gives no transaction id, but (team, date,
-- description) is effectively unique in practice -- re-fetching the same
-- season and re-inserting is then a no-op via ON CONFLICT DO NOTHING (see
-- transactions_repo.insert_transaction). NULLS NOT DISTINCT (PG15+, this
-- repo runs postgres:16) so an unresolved team_id still dedupes on
-- (NULL, transaction_date, description) -- without it, standard SQL NULL
-- semantics treat every NULL as distinct from every other NULL, which
-- would silently defeat the constraint for every unresolved-team row (a
-- real idempotency gap, not just a false-collision risk) on every re-run.
-- The remaining, accepted edge case is coarser: two genuinely DIFFERENT
-- unresolved teams announcing the identical description on the identical
-- date would collide and the second insert would be dropped -- deliberately
-- not worth a more complex key for a two-teams-same-day-verbatim-text
-- coincidence this unlikely.
CREATE UNIQUE INDEX player_transactions_team_date_description_idx
    ON player_transactions (team_id, transaction_date, description) NULLS NOT DISTINCT;

CREATE INDEX player_transactions_transaction_date_idx ON player_transactions (transaction_date);
CREATE INDEX player_transactions_player_id_idx ON player_transactions (player_id);
