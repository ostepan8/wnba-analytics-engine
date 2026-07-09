-- Distinguishes real WNBA franchises from the exhibition/All-Star rosters
-- and international opponents that also show up in the teams table (e.g.
-- "Team Wilson"/"Team Stewart" for the All-Star game, "Brazil"/"Japan" for
-- preseason exhibitions). Needed so validation can flag any non-franchise
-- team appearing in a *regular-season* game -- exactly the class of bug
-- that let 4 All-Star games get ingested as regular-season (see the ESPN
-- parser's competition.type handling), with "Team Wilson" etc. polluting
-- this table as if they were real franchises.
--
-- Defaults to false: a new team is only a recognized franchise once
-- explicitly flagged here, same as this backfill does for the current
-- roster of 15 franchises (13 active + Portland Fire/Toronto Tempo, both
-- joining as 2026 expansion teams).
ALTER TABLE teams ADD COLUMN is_franchise BOOLEAN NOT NULL DEFAULT false;

UPDATE teams SET is_franchise = true
WHERE abbreviation IN (
    'ATL', 'CHI', 'CON', 'DAL', 'GS', 'IND', 'LV', 'LA', 'MIN', 'NY',
    'PHX', 'SEA', 'WSH', 'TOR', 'POR'
);
