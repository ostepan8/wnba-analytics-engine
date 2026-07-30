-- When we first observed a game as FINAL.
--
-- `games.start_time` records when a game TIPPED OFF. Nothing recorded when
-- its result became knowable, which is the timestamp any point-in-time
-- feature build actually needs: filtering on `start_time <= as_of` admits
-- a game that started twenty minutes before the boundary and finished two
-- hours after it, and its final score -- which nobody could have known --
-- becomes a model input.
--
-- The feature layer worked around this with a fixed four-hour margin
-- (wnba_engine/features/steps/loading.py). That is a guess. This column
-- replaces the guess with an observation wherever one exists.
--
-- No upstream provider offers a game-end timestamp. Verified live: ESPN's
-- summary reports status.type.completed = true with no completion time,
-- only the start `date`; game_plays.clock is GAME clock, not wall clock;
-- odds_api_game_scores.captured_at is our own capture, and covers 18 games.
-- So the honest available signal is when OUR pipeline witnessed the
-- transition.
--
-- SET ONLY ON A WITNESSED TRANSITION -- when a game we already had as
-- non-final is re-synced and is now final. Deliberately NOT set when a
-- game is first inserted already final, because that tells us nothing
-- about when the result became knowable: a 2022 backfill run today would
-- otherwise stamp every historical game with 2026 and make the entire
-- archive look unknowable until now. Those rows stay NULL and fall back
-- to the margin, which is why the margin survives rather than being
-- deleted.
--
-- Never overwritten once set. A later re-sync of an already-final game
-- must not move the timestamp forward; the first observation is the
-- honest one.
--
-- Consequence worth stating plainly: this only improves games ingested
-- from now on. Historical rows are NULL forever, because the information
-- was never recorded and cannot be reconstructed.

ALTER TABLE games
    ADD COLUMN final_observed_at TIMESTAMPTZ;

COMMENT ON COLUMN games.final_observed_at IS
    'When our pipeline first saw this game as final. NULL when the game was '
    'already final on first ingest (a backfill), since that says nothing '
    'about when the result became knowable. Never overwritten.';
