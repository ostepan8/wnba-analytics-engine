-- Forward log of cross-venue divergences, for the one open question.
--
-- MODELING_FINDINGS.md establishes the effect and cannot establish whether
-- it is tradeable. The gap is not statistical, it is temporal: every
-- divergence in the historical data was observed up to an hour late,
-- because sportsbook captures were ~60 minutes apart and the price moves
-- inside that gap. A backtest cannot close that; only a forward log at the
-- capture cadence can.
--
-- Two questions, hence two groups of columns:
--
--   1. WAS THE PRICE STILL THERE?  Written by a later pass that re-reads
--      the same book at the next capture. This is the executability
--      question and it is the reason the table exists.
--
--   2. WAS IT A GOOD PRICE?  Closing line and outcome, so CLV can be
--      graded forward rather than inferred. CLV reaches t=3 in ~120
--      observations where ROI needs ~10,600, so this is the metric that
--      will actually resolve within a season.
--
-- Grading columns are NULLABLE and written later. A row is inserted the
-- moment a divergence is seen and never rewritten except to fill these in,
-- which keeps the observation itself append-only and honest: what we
-- thought at the time cannot be edited by what happened afterwards.

CREATE TABLE divergence_observations (
    id                  BIGSERIAL PRIMARY KEY,

    -- The observation.
    game_id             BIGINT      NOT NULL REFERENCES games(id),
    observed_at         TIMESTAMPTZ NOT NULL,
    venue               TEXT        NOT NULL CHECK (venue IN ('polymarket','kalshi')),
    side                TEXT        NOT NULL CHECK (side IN ('home','away')),

    book_vendor         TEXT        NOT NULL,
    book_odds           INTEGER     NOT NULL,
    book_implied        NUMERIC(8,6) NOT NULL,

    venue_fair          NUMERIC(8,6) NOT NULL,
    venue_volume        NUMERIC(18,6) NOT NULL,
    venue_trade_count   INTEGER     NOT NULL,

    -- venue_fair - book_implied. Positive by construction; stored rather
    -- than derived so a later change to the detector cannot silently
    -- restate what was recorded at the time.
    edge                NUMERIC(8,6) NOT NULL,

    -- (1) executability, filled by grade-divergences
    recheck_at          TIMESTAMPTZ,
    recheck_odds        INTEGER,
    price_survived      BOOLEAN,

    -- (2) value, filled after the game
    closing_odds        INTEGER,
    closing_implied     NUMERIC(8,6),
    clv                 NUMERIC(8,6),
    won                 BOOLEAN,
    graded_at           TIMESTAMPTZ,

    captured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- House convention: this stores repeated OBSERVATIONS of mutable
    -- state, so observation time belongs in the key. (Contrast
    -- 0025_prediction_market_history.sql, which stores immutable facts and
    -- deliberately excludes it.) One row per moment, venue and side; the
    -- best book is an attribute of that row, not part of its identity,
    -- because re-running the detector must not create a second row when a
    -- different book happens to be best.
    CONSTRAINT divergence_observations_moment_key
        UNIQUE (game_id, observed_at, venue, side)
);

-- Ungraded rows, oldest first: the access pattern of both grading passes.
CREATE INDEX divergence_observations_ungraded_idx
    ON divergence_observations (observed_at)
    WHERE graded_at IS NULL;

CREATE INDEX divergence_observations_game_idx
    ON divergence_observations (game_id);
