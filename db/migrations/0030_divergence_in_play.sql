-- Tag each divergence with whether the game was under way, and how far in.
--
-- The log was built for the pre-tip window because that is where
-- MODELING_FINDINGS.md measured the effect. Checking the volume split on
-- 2026-08-06 showed that window is the MINORITY of the market: 65.3% of
-- Polymarket size and 78.1% of Kalshi size trades after tip-off.
--
-- A first pass over the 3,888 in-play sportsbook rows captured incidentally
-- (the hourly snapshot never filtered by tip) found divergence in 54.3% of
-- liquid moments at a 3.04% median edge, against 13.3% and 0.55% pre-tip.
--
-- That is either the real opportunity or an artifact, and the two are hard
-- to tell apart from history: in-play a book's quoted price goes stale
-- within seconds of a scoring play, so a large "edge" is exactly what a
-- price that no longer exists looks like. Pre-tip nothing moves fast enough
-- for staleness to matter, which is why the same measurement is trustworthy
-- there and suspect here.
--
-- Hence these columns rather than a separate table: the discriminator is
-- `price_survived`, which the log already records, and the whole question
-- is whether survival differs between the two regimes. Same rows, same
-- grading, one flag to split on.

ALTER TABLE divergence_observations
    ADD COLUMN in_play BOOLEAN NOT NULL DEFAULT false,
    -- Signed minutes from tip-off: negative before, positive after. Kept
    -- as well as the boolean because "two minutes before tip" and "six
    -- hours before tip" are not the same pre-tip, and neither are the
    -- first and last minutes of a game.
    ADD COLUMN minutes_from_tip NUMERIC(8,2);

CREATE INDEX divergence_observations_in_play_idx
    ON divergence_observations (in_play, observed_at);
