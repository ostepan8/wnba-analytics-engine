-- Recoverable prediction-market history: Polymarket fills and Kalshi bars.
--
-- AGENTS.md has said since the capture host was built that Kalshi and
-- Polymarket are "current-state only, with no historical endpoint" and that
-- an observation not recorded at the time is "gone forever". That was wrong,
-- and the cost of believing it was a 14-day July 2026 outage written off as
-- unrecoverable. Verified live on 2026-08-03:
--
--   * https://data-api.polymarket.com/trades?market=<conditionId>
--     returns every on-chain fill, paginated, back to 2024-09-20 for WNBA.
--     Tested against the Seattle/Dallas game that closed 2026-06-02: 717
--     trades spanning 2026-05-26 .. 2026-06-02. The CLOB's /prices-history
--     returns ZERO points for that same market -- it is a rolling ~30-day
--     cache, not an archive, which is what made the feed look unrecoverable.
--
--   * https://api.elections.kalshi.com/trade-api/v2/series/{s}/markets/{t}/candlesticks
--     returns OHLC bars back to market creation (a season future opened
--     2026-05-22 still returns its first bar when asked for 180 days).
--
-- So both feeds ARE recoverable, and these two tables hold what the snapshot
-- capture cannot: what actually traded, rather than what was quoted when a
-- 30-minute cron happened to look.
--
-- IDEMPOTENCY DEVIATES FROM THE HOUSE CONVENTION, deliberately. Every other
-- append-only table here is keyed UNIQUE(<external identity>, captured_at)
-- because it stores repeated OBSERVATIONS of mutable state. These two store
-- immutable historical FACTS: a fill happened once, at one instant, on one
-- chain; a closed candlestick never changes. Re-fetching must be a no-op
-- regardless of when we fetched, so captured_at is recorded but is NOT part
-- of the key. Including it would let one backfill run duplicate every row of
-- the previous one -- the exact failure UNIQUE(...) exists to prevent.

CREATE TABLE polymarket_trades (
    id                BIGSERIAL PRIMARY KEY,
    -- On-chain identity. transactionHash alone is nearly unique (500/500
    -- distinct in the sample above) but NOT guaranteed to be: both sides of
    -- a Polymarket trade record separately, and a batched transaction can
    -- carry several fills. Keying on the participating wallet, the token,
    -- and the direction as well makes a genuine multi-fill transaction
    -- storable while still rejecting a re-fetch.
    transaction_hash  TEXT NOT NULL,
    proxy_wallet      TEXT NOT NULL,
    asset             TEXT NOT NULL,
    side              TEXT NOT NULL,
    condition_id      TEXT NOT NULL,
    -- The outcome as a TEAM NAME ("Seattle Storm"), stated by the API rather
    -- than inferred. market_price_snapshots cannot do this: Gamma's
    -- groupItemTitle is null for two-way game markets, so which side its
    -- implied_probability describes had to be reverse-engineered against
    -- resolved games (77.8% agreement over 27 games -- suggestive, not a
    -- fact). Here it is in the payload, so the ambiguity does not exist.
    outcome           TEXT,
    outcome_index     INTEGER,
    price             NUMERIC(10, 6) NOT NULL,
    size              NUMERIC(20, 6) NOT NULL,
    traded_at         TIMESTAMPTZ NOT NULL,
    title             TEXT,
    slug              TEXT,
    event_slug        TEXT,
    game_id           BIGINT REFERENCES games (id),
    captured_at       TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT polymarket_trades_fill_key
        UNIQUE (transaction_hash, proxy_wallet, asset, side)
);

-- Backfill walks one condition_id at a time and the analysis layer reads one
-- game at a time; both are covered here. traded_at leads the game_id index
-- because every point-in-time query filters on it.
CREATE INDEX polymarket_trades_condition_idx ON polymarket_trades (condition_id, traded_at);
CREATE INDEX polymarket_trades_game_idx ON polymarket_trades (game_id, traded_at)
    WHERE game_id IS NOT NULL;

CREATE TABLE kalshi_candlesticks (
    id                BIGSERIAL PRIMARY KEY,
    series_ticker     TEXT NOT NULL,
    market_ticker     TEXT NOT NULL,
    -- period_interval as Kalshi names it, in minutes. Part of the key
    -- because the same instant is legitimately covered by a 1-minute and a
    -- 60-minute bar, and storing both must not be a conflict.
    period_minutes    INTEGER NOT NULL,
    period_end        TIMESTAMPTZ NOT NULL,
    -- Kalshi quotes dollar STRINGS ("0.1600"), not numbers, and splits the
    -- bar three ways: traded price, and separately the yes_bid and yes_ask
    -- books. Keeping bid and ask rather than a midpoint is the whole reason
    -- this table is worth having over a price series -- spread is how you
    -- tell a real quote from an empty book, and the empty ones are exactly
    -- what poisons a lead-lag study.
    price_open        NUMERIC(10, 6),
    price_high        NUMERIC(10, 6),
    price_low         NUMERIC(10, 6),
    price_close       NUMERIC(10, 6),
    price_mean        NUMERIC(10, 6),
    price_previous    NUMERIC(10, 6),
    yes_bid_open      NUMERIC(10, 6),
    yes_bid_high      NUMERIC(10, 6),
    yes_bid_low       NUMERIC(10, 6),
    yes_bid_close     NUMERIC(10, 6),
    yes_ask_open      NUMERIC(10, 6),
    yes_ask_high      NUMERIC(10, 6),
    yes_ask_low       NUMERIC(10, 6),
    yes_ask_close     NUMERIC(10, 6),
    volume            NUMERIC(20, 6),
    open_interest     NUMERIC(20, 6),
    game_id           BIGINT REFERENCES games (id),
    captured_at       TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT kalshi_candlesticks_bar_key
        UNIQUE (market_ticker, period_minutes, period_end)
);

CREATE INDEX kalshi_candlesticks_series_idx
    ON kalshi_candlesticks (series_ticker, period_end);
CREATE INDEX kalshi_candlesticks_game_idx ON kalshi_candlesticks (game_id, period_end)
    WHERE game_id IS NOT NULL;
