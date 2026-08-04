-- Kalshi trade history, from the HISTORICAL tier.
--
-- Found only because someone asked whether a bulk dataset existed outside
-- the API. It does not, but something better does: Kalshi partitions its
-- exchange data into a live tier and a historical one past a cutoff
-- (2026-06-05 as of writing, GET /historical/cutoff), and every query in
-- this project had been hitting the live tier alone.
--
-- The difference is a whole season. `/markets?series_ticker=KXWNBAGAME`
-- returns 364 settled markets, earliest close 2026-05-22.
-- `/historical/markets` returns 760, earliest close **2025-05-23** --
-- including the 2025 Finals. Every Kalshi conclusion in
-- MODELING_FINDINGS.md was drawn from one partial season because the other
-- one was behind a different path.
--
-- Candlesticks 404 for those older markets, but `/historical/trades` does
-- not: it returns trade-level records with `trade_id`, `created_time`,
-- `yes_price_dollars` and size. So this is the Kalshi analogue of
-- polymarket_trades, and it is keyed the same way and for the same reason
-- (0025): a trade is an immutable fact, so `trade_id` alone is the natural
-- key and captured_at is recorded but deliberately not part of it.
--
-- These markets are liquid in a way the Polymarket ones are not -- median
-- 112,951 contracts per 2025 market, max 3,374,424 -- which makes them the
-- better venue for anything sensitive to whether a price was real.

CREATE TABLE kalshi_trades (
    id             BIGSERIAL PRIMARY KEY,
    trade_id       TEXT NOT NULL,
    market_ticker  TEXT NOT NULL,
    series_ticker  TEXT,
    -- The YES side's price, already a probability: Kalshi contracts settle
    -- at $0 or $1. Stored as the yes price regardless of which side the
    -- taker was on, so a series is directly comparable across trades.
    yes_price      NUMERIC(10, 6) NOT NULL,
    no_price       NUMERIC(10, 6),
    -- Contracts, not dollars. Notional is yes_price * size.
    size           NUMERIC(20, 6),
    taker_side     TEXT,
    is_block_trade BOOLEAN,
    traded_at      TIMESTAMPTZ NOT NULL,
    game_id        BIGINT REFERENCES games (id),
    captured_at    TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT kalshi_trades_trade_key UNIQUE (trade_id)
);

CREATE INDEX kalshi_trades_market_idx ON kalshi_trades (market_ticker, traded_at);
CREATE INDEX kalshi_trades_game_idx ON kalshi_trades (game_id, traded_at)
    WHERE game_id IS NOT NULL;
