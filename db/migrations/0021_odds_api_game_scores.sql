-- the-odds-api final scores (/v4/sports/basketball_wnba/scores) -- a
-- second, INDEPENDENT source of completed-game final scores, captured
-- purely as a cross-check against games.home_score/away_score.
--
-- db/migrations/0001_canonical_entities.sql documents that the-odds-api is
-- *intended* to eventually outrank ESPN for final scores -- that
-- precedence change is deliberately NOT made here. This table only feeds
-- a new validation check (check_odds_api_score_matches_game_score in
-- wnba_engine/validation/consistency_checks.py) that surfaces
-- disagreements for human review; games.home_score/away_score is never
-- written from this pipeline.
--
-- Append-only, same UNIQUE(external_id, captured_at) idempotency
-- convention as sportsbook_game_odds (0014_balldontlie_odds.sql):
-- captured_at is the row's own the-odds-api `last_update` (verified live
-- this can be ~10h after commence_time -- the score settles well after
-- the final buzzer), not our ingest wall-clock, so a genuine score
-- correction from the provider lands as a new history row rather than
-- silently overwriting a prior capture.

CREATE TABLE odds_api_game_scores (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_id  TEXT NOT NULL,      -- the-odds-api's own event id
    game_id      BIGINT NOT NULL REFERENCES games (id),
    home_score   INT NOT NULL,
    away_score   INT NOT NULL,
    captured_at  TIMESTAMPTZ NOT NULL,

    UNIQUE (external_id, captured_at)
);

CREATE INDEX odds_api_game_scores_game_idx ON odds_api_game_scores (game_id);
