-- Player biographical data from balldontlie (paid GOAT tier). Present on
-- the "player" object of every advanced-stats and shot-zone response we
-- already ingest, but discarded until now -- only full_name/position were
-- ever promoted to the canonical players table.
--
-- Types verified live against api.balldontlie.io/wnba/v1: height/weight
-- are free-text ("6' 1\"", "160 lbs"), NOT numeric inches/pounds -- stored
-- as TEXT, not converted. jersey_number is also free text (values like
-- "0" and "00" are both valid jersey numbers, so it is not an INT).
-- college is free text. age is a genuine integer.
--
-- balldontlie represents "unknown" two different ways depending on the
-- field: some rows have real JSON null (height/weight/college/age all
-- null together), others use the in-band placeholder string "--" for an
-- otherwise-populated row (e.g. weight/college for an international
-- player with no draft-combine measurement on file). Both are normalized
-- to SQL NULL by wnba_engine.parsing.optional_str/optional_int before
-- reaching this table -- "--" is never stored literally.
ALTER TABLE players
    ADD COLUMN height TEXT,
    ADD COLUMN weight TEXT,
    ADD COLUMN jersey_number TEXT,
    ADD COLUMN college TEXT,
    ADD COLUMN age INT;
