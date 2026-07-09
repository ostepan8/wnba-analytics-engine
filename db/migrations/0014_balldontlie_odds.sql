-- balldontlie sportsbook odds: /wnba/v1/odds (game-level moneyline/spread/
-- total) and /wnba/v1/odds/player_props (player prop lines).
--
-- IMPORTANT -- this repo now has TWO different "odds" concepts, and they
-- are NOT interchangeable:
--
--   * market_price_snapshots (0003_market_price_snapshots.sql) is Kalshi /
--     Polymarket PREDICTION-MARKET data: peer-to-peer yes/no contracts
--     traded on an order book, where price (0-1) already IS an implied
--     probability.
--   * sportsbook_game_odds / sportsbook_player_prop_odds (this migration)
--     are traditional SPORTSBOOK odds from a real bookmaker (DraftKings,
--     FanDuel, ...), quoted in American odds format (e.g. -120, +900) --
--     not probabilities, not peer-to-peer, and often several bookmakers
--     quoting the SAME game/prop with different lines simultaneously.
--
-- See wnba_engine/models/odds.py for the fuller explanation. Two separate
-- tables (not one polymorphic table, and not folded into
-- market_price_snapshots) because the game-level and player-prop payloads
-- have meaningfully different shapes (moneyline/spread/total columns vs.
-- stat-line/over-under columns) -- forcing them into one row shape would
-- mean a wall of always-null columns on every row.
--
-- Append-only time series, matching market_price_snapshots' philosophy
-- (odds movement is signal, not noise -- we want history, not just the
-- latest quote). Unlike market_price_snapshots' captured_at (our own
-- ingest wall-clock), captured_at here is balldontlie's own `updated_at`
-- field on each row (verified live: every row carries one) -- a genuine
-- source-side "as of" timestamp, so a UNIQUE(external_id, captured_at)
-- constraint makes re-running a backfill over an unchanged window a true
-- no-op (ON CONFLICT DO NOTHING) instead of piling up identical duplicate
-- rows, while a real line movement (new updated_at for the same
-- external_id) still lands as a new history row.
--
-- game_id/player_id are NOT NULL (unlike market_price_snapshots' nullable
-- game_id, which allows futures markets with no single game): every odds
-- row here always names a specific balldontlie game_id (and, for props, a
-- player_id) in the source payload, so an unresolved crosswalk means the
-- row is skipped at ingest time rather than stored with a dangling NULL --
-- same convention the advanced-stats/plays/shot-zone balldontlie pipelines
-- already use for unresolved games/teams.

CREATE TABLE sportsbook_game_odds (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source               TEXT NOT NULL DEFAULT 'balldontlie',
    external_id          TEXT NOT NULL,      -- balldontlie's own odds-row id
    game_id              BIGINT NOT NULL REFERENCES games (id),
    vendor               TEXT NOT NULL,      -- 'draftkings' | 'fanduel' | 'fanatics' | 'caesars' | 'betmgm' | 'betrivers' | ...

    spread_home_value    NUMERIC(6, 1),
    spread_home_odds     INT,
    spread_away_value    NUMERIC(6, 1),
    spread_away_odds     INT,

    moneyline_home_odds  INT,
    moneyline_away_odds  INT,

    total_value          NUMERIC(6, 1),
    total_over_odds      INT,
    total_under_odds     INT,

    captured_at          TIMESTAMPTZ NOT NULL,  -- balldontlie's own 'updated_at', not ingest wall-clock

    UNIQUE (external_id, captured_at)
);

CREATE INDEX sportsbook_game_odds_game_idx ON sportsbook_game_odds (game_id);
CREATE INDEX sportsbook_game_odds_captured_at_idx ON sportsbook_game_odds (captured_at);

CREATE TABLE sportsbook_player_prop_odds (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        TEXT NOT NULL DEFAULT 'balldontlie',
    external_id   TEXT NOT NULL,      -- balldontlie's own prop-odds-row id
    game_id       BIGINT NOT NULL REFERENCES games (id),
    player_id     BIGINT NOT NULL REFERENCES players (id),
    vendor        TEXT NOT NULL,

    prop_type     TEXT NOT NULL,      -- 'points' | 'rebounds' | 'assists' | ... | 'double_double' | 'triple_double'
    line_value    NUMERIC(6, 1) NOT NULL,

    -- Two mutually-exclusive market shapes in the same payload (see
    -- wnba_engine/models/odds.py PlayerPropOddsRow): 'milestone' populates
    -- `odds` only, 'over_under' populates over_odds/under_odds only.
    market_type   TEXT NOT NULL,      -- 'milestone' | 'over_under'
    odds          INT,
    over_odds     INT,
    under_odds    INT,

    captured_at   TIMESTAMPTZ NOT NULL,

    UNIQUE (external_id, captured_at)
);

CREATE INDEX sportsbook_player_prop_odds_game_idx ON sportsbook_player_prop_odds (game_id);
CREATE INDEX sportsbook_player_prop_odds_player_idx ON sportsbook_player_prop_odds (player_id);
CREATE INDEX sportsbook_player_prop_odds_captured_at_idx ON sportsbook_player_prop_odds (captured_at);
