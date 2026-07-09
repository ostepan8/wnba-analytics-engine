-- Player-prop crosswalk: resolves a market snapshot to the player it's
-- about (independent of game_id, which stays NULL if the player's game
-- can't be pinned down -- see wnba_engine/repositories/entity_repo.py
-- find_recent_team_id_for_player / find_game_id_by_team_and_date).

ALTER TABLE market_price_snapshots
    ADD COLUMN player_id BIGINT REFERENCES players (id);

CREATE INDEX market_price_snapshots_player_idx
    ON market_price_snapshots (player_id) WHERE player_id IS NOT NULL;
