-- Prediction-market price snapshots (Kalshi, Polymarket, ...).
-- Append-only time series: every ingestion run inserts new rows, never
-- updates old ones — we want price *history*, not just the latest quote.
-- All prices are normalized to implied probabilities in [0, 1].

CREATE TABLE market_price_snapshots (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider            TEXT NOT NULL,          -- 'kalshi' | 'polymarket'
    market_external_id  TEXT NOT NULL,          -- Kalshi market ticker / Gamma market id
    event_external_id   TEXT,                   -- Kalshi event ticker / Gamma event id
    -- Nullable on purpose: futures/award markets don't map to one game.
    -- Game mapping is resolved via provider_entity_map when possible.
    game_id             BIGINT REFERENCES games (id),
    title               TEXT NOT NULL,          -- market question, e.g. "Indiana vs Phoenix winner?"
    outcome             TEXT,                   -- e.g. "Phoenix", "Atlanta Dream"
    yes_bid             NUMERIC(8, 6),
    yes_ask             NUMERIC(8, 6),
    last_price          NUMERIC(8, 6),
    implied_probability NUMERIC(8, 6),
    volume              NUMERIC(18, 4),
    liquidity           NUMERIC(18, 4),
    open_interest       NUMERIC(18, 4),
    status              TEXT NOT NULL,
    close_time          TIMESTAMPTZ,
    captured_at         TIMESTAMPTZ NOT NULL
);

CREATE INDEX market_price_snapshots_market_time_idx
    ON market_price_snapshots (provider, market_external_id, captured_at);
CREATE INDEX market_price_snapshots_game_idx
    ON market_price_snapshots (game_id) WHERE game_id IS NOT NULL;
CREATE INDEX market_price_snapshots_captured_at_idx
    ON market_price_snapshots (captured_at);
