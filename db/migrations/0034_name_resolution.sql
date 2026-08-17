-- Candidate generation and a decision log for resolving a player NAME.
--
-- Several sources identify a player by name alone and by no id at all: the
-- league's injury-report PDF ("Parker- Tyus, Cheyenne"), Kalshi and Polymarket
-- prop titles, archived injury pages. Matching those to the canonical player is
-- where this project has been wrong before -- 43% of prop rows once carried the
-- wrong player, repaired in 0033 -- so the rule since then is that an
-- unresolved name is dropped rather than guessed.
--
-- Dropping is safe but lossy: a name we cannot match is a player missing from
-- the report entirely. Two things here narrow that gap without loosening the
-- rule.
--
-- pg_trgm gives real candidate generation. Exact, diacritic-folded and
-- reversed-order matching all fail on "Parker- Tyus" because the PDF's text
-- layer split the surname; trigram similarity ranks the right player first
-- anyway, which turns "no match" into "a short list to choose from".
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS players_full_name_trgm_idx
    ON players USING gin (full_name gin_trgm_ops);

-- The decision log. Every resolution that was NOT a plain deterministic match
-- is recorded here with how it was decided, so that:
--
--   * a name is resolved once rather than on every 2-hourly ingest,
--   * a wrong call is auditable and correctable in one place instead of being
--     baked invisibly into a fact table, and
--   * `player_id IS NULL` is a real answer -- "we looked and declined" -- which
--     stops us re-asking about a name that genuinely has no match.
CREATE TABLE IF NOT EXISTS player_name_resolutions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_name      text        NOT NULL,
    -- What the name was seen alongside: usually a team abbreviation. The same
    -- string can be two people across seasons; context is what disambiguates.
    context       text        NOT NULL DEFAULT '',
    source        text        NOT NULL,
    player_id     bigint      REFERENCES players(id),
    -- 'deterministic' | 'llm' | 'manual'. Never blank: knowing HOW a row was
    -- decided is the difference between an audit and a guess.
    method        text        NOT NULL,
    -- The model that decided it, when method = 'llm'. A future model change
    -- should be able to find and revisit only its own predecessor's calls.
    model         text,
    -- The candidates that were offered, so a bad call can be re-examined
    -- against what was actually on the table at the time.
    candidates    jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, raw_name, context)
);

CREATE INDEX IF NOT EXISTS player_name_resolutions_player_idx
    ON player_name_resolutions (player_id);
