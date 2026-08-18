"""Read-only queries behind the HTTP API.

All SQL lives in repositories/ (AGENTS.md), including the read side, so there
is exactly one place to look when a column moves. Nothing here writes.

Every query takes a bounded limit. The tables these read from are append-only
price and play history -- market_price_snapshots alone is ~880k rows and grows
every two minutes -- so an unbounded SELECT is a matter of when, not if.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection

# Hard ceiling applied to every caller-supplied limit. The API validates its own
# query parameters, but this is the layer that actually touches the database and
# it does not trust a caller to have done that.
# Exhibitions are excluded from every season figure on this page.
#
# games.season_type distinguishes regular-season and post-season play from
# `preseason` (WNBA teams host national sides in April/May -- Indiana beat
# Nigeria 105-57 in 2026) and `other` (the All-Star game). Those are real rows
# with real box scores, and counting them silently corrupts everything derived
# from a season: records, points for and against, player averages, defence by
# position, and every ATS/over-under record graded against a line that was
# never a real market. The modelling layer (style_repo, feature_repo) always
# filtered; this display layer did not, which is how a 48-point win over a
# national team ended up inside a team's scoring average.
#
# Post-season is kept: playoff games are real games.

MAX_ROWS = 500

# Kalshi's full-game winner series. The same series the ingest and trade-backfill
# pipelines treat as the moneyline (wnba_engine/pipeline/kalshi_trade_backfill.py).
#
# Filtering on it is not optional. Kalshi's per-quarter winner markets
# (KXWNBA1QWINNER…KXWNBA4QWINNER) carry the SAME `outcome` value and a title that
# differs only past the truncation point -- "Portland vs Phoenix women's Pro
# Basketball game: Phoenix wins" vs "…: Phoenix wins the 1st quarter". Matching on
# the team label alone therefore pulls five unrelated markets into one line, which
# renders as a price "spiking" between 0.005 and 0.995 several times a minute.
KALSHI_GAME_SERIES_PREFIX = "KXWNBAGAME-"

_SUMMARY = """
SELECT
    (SELECT count(*) FROM games)                        AS games,
    (SELECT count(*) FROM games WHERE status = 'final') AS games_final,
    (SELECT count(*) FROM teams)                        AS teams,
    (SELECT count(*) FROM players)                      AS players,
    (SELECT count(*) FROM market_price_snapshots)       AS market_price_snapshots,
    (SELECT count(*) FROM sportsbook_game_odds)         AS sportsbook_game_odds,
    (SELECT count(*) FROM divergence_observations)      AS divergence_observations,
    (SELECT min(start_time) FROM games)                 AS earliest_game,
    (SELECT max(start_time) FROM games)                 AS latest_game,
    (SELECT max(captured_at) FROM market_price_snapshots) AS latest_market_price,
    (SELECT max(captured_at) FROM sportsbook_game_odds)   AS latest_sportsbook_odds
"""

_RECENT_GAMES = """
SELECT g.id, g.season, g.season_type, g.start_time, g.status,
       g.home_score, g.away_score, g.venue_name,
       -- The ids, not just the names: a client cannot render a team's logo or
       -- link to it from an abbreviation, and looking one up per row would turn
       -- a schedule into a hundred extra requests.
       g.home_team_id, g.away_team_id,
       home.name AS home_team, home.abbreviation AS home_abbr,
       away.name AS away_team, away.abbreviation AS away_abbr
  FROM games g
  JOIN teams home ON home.id = g.home_team_id
  JOIN teams away ON away.id = g.away_team_id
-- The casts are required, not stylistic. Postgres cannot infer a type for a
-- parameter whose only use is `$1 IS NULL`, and errors with AmbiguousParameter
-- when the optional filter is omitted.
 WHERE (%(season)s::int  IS NULL OR g.season = %(season)s::int)
   AND (%(since)s::date  IS NULL OR g.start_time >= %(since)s::date)
 ORDER BY g.start_time DESC
 LIMIT %(limit)s
"""

_GAME_BY_ID = """
SELECT g.id, g.season, g.season_type, g.start_time, g.status,
       g.home_score, g.away_score, g.venue_name, g.attendance,
       g.home_team_id, g.away_team_id,
       home.name AS home_team, home.abbreviation AS home_abbr,
       away.name AS away_team, away.abbreviation AS away_abbr
  FROM games g
  JOIN teams home ON home.id = g.home_team_id
  JOIN teams away ON away.id = g.away_team_id
 WHERE g.id = %(game_id)s
"""

# Line movement for one game. Ordered forward in time because a chart reads
# left to right; the LIMIT is a safety rail, not a window -- a heavily covered
# game accumulates a few hundred rows across vendors.
_GAME_ODDS_HISTORY = """
SELECT vendor, captured_at,
       moneyline_home_odds, moneyline_away_odds,
       spread_home_value, spread_home_odds,
       total_value, total_over_odds, total_under_odds
  FROM sportsbook_game_odds
 WHERE game_id = %(game_id)s
 ORDER BY captured_at
 LIMIT %(limit)s
"""

# Prediction-market MONEYLINE prices for one game, resolved to a side.
#
# The filter is the whole point. market_price_snapshots holds every market a
# venue lists for a game -- player props, quarter and half totals, spreads,
# winning margins, overtime, "Tie". For one August 2026 game that is 118
# distinct outcomes. Selecting the game's rows and plotting them as a price
# series produces a chart that means nothing at all.
#
# So a row is kept only if its `outcome` exactly matches one of the two teams,
# by full name, city, or nickname -- "Phoenix Mercury", "Phoenix", "Mercury".
# That is the idiom already used in wnba_engine/pipeline/divergence_log.py; the
# extra city form is needed because Kalshi labels its moneyline by city while
# Polymarket's trade feed uses the nickname. Exact matching is what keeps
# "Phoenix wins 1st half" and "Phoenix wins by over 4.5 points" out.
#
# `side` is returned rather than derived by the caller, so normalising two
# venues onto one home-win-probability axis does not require a client to
# re-implement team matching.
#
# Polymarket's combined game market carries a NULL outcome and a single price
# whose side is not recoverable from this table; it is excluded rather than
# guessed at. Its side-resolved equivalent lives in polymarket_trades, which
# the divergence pipeline uses.
_GAME_MARKET_PRICES = """
SELECT s.provider, s.market_external_id, s.outcome, s.implied_probability,
       s.last_price, s.volume, s.captured_at,
       CASE WHEN s.outcome IN (
                h.name,
                split_part(h.name, ' ', 1),
                split_part(h.name, ' ', array_length(string_to_array(h.name, ' '), 1))
            ) THEN 'home' ELSE 'away' END AS side
  FROM market_price_snapshots s
  JOIN games g ON g.id = s.game_id
  JOIN teams h ON h.id = g.home_team_id
  JOIN teams a ON a.id = g.away_team_id
 WHERE s.game_id = %(game_id)s
   AND s.implied_probability IS NOT NULL
   -- Full-game winner only. Kalshi's quarter-winner markets are otherwise
   -- indistinguishable from it by outcome or title; see the constant above.
   AND (s.provider <> 'kalshi'
        OR s.market_external_id LIKE %(kalshi_prefix)s)
   AND (
        s.outcome IN (
            h.name,
            split_part(h.name, ' ', 1),
            split_part(h.name, ' ', array_length(string_to_array(h.name, ' '), 1))
        )
     OR s.outcome IN (
            a.name,
            split_part(a.name, ' ', 1),
            split_part(a.name, ' ', array_length(string_to_array(a.name, ' '), 1))
        )
   )
 ORDER BY s.captured_at
 LIMIT %(limit)s
"""

# The forward divergence log. Joined to teams so a row is readable without a
# second lookup -- this feeds a table in the UI, not a join in a notebook.
_DIVERGENCES = """
SELECT d.id, d.game_id, d.observed_at, d.venue, d.side, d.in_play,
       d.book_vendor, d.book_odds, d.book_implied,
       d.venue_fair, d.venue_volume, d.edge, d.minutes_from_tip,
       d.price_survived, d.recheck_odds, d.clv, d.won, d.graded_at,
       home.abbreviation AS home_abbr, away.abbreviation AS away_abbr,
       g.start_time
  FROM divergence_observations d
  JOIN games g    ON g.id = d.game_id
  JOIN teams home ON home.id = g.home_team_id
  JOIN teams away ON away.id = g.away_team_id
 WHERE (%(venue)s::text IS NULL OR d.venue = %(venue)s::text)
   AND (%(graded_only)s::boolean IS NOT TRUE OR d.graded_at IS NOT NULL)
 ORDER BY d.observed_at DESC
 LIMIT %(limit)s
"""

# Aggregate view of the log's two open questions: was the price still there
# (price_survived), and was it a good price (clv, won).
#
# The counts are reported alongside every rate on purpose. MODELING_FINDINGS.md
# is explicit that CLV reaches significance around 120 observations and ROI
# needs ~10,600 -- a survival rate quoted without its denominator invites
# exactly the over-reading this project is trying to avoid.
_DIVERGENCE_SUMMARY = """
SELECT
    venue,
    count(*)                                              AS observations,
    count(*) FILTER (WHERE graded_at IS NOT NULL)         AS graded,
    count(*) FILTER (WHERE price_survived)                AS price_survived,
    count(*) FILTER (WHERE price_survived IS NOT NULL)    AS survival_checked,
    round(avg(edge)::numeric, 4)                          AS mean_edge,
    round(avg(clv)::numeric, 4)                           AS mean_clv,
    count(*) FILTER (WHERE clv IS NOT NULL)               AS clv_graded,
    count(*) FILTER (WHERE won)                           AS won,
    count(*) FILTER (WHERE won IS NOT NULL)               AS settled
  FROM divergence_observations
 GROUP BY venue
 ORDER BY venue
"""

# League standings, with what is needed to work out the playoff race.
#
# `playoff_seed` is returned as CONFERENCE_SEED, not seed. It is the provider's
# conference ranking -- 1-8 West, 1-7 East in 2026 -- and the WNBA has seeded
# its postseason league-wide since 2016. Renaming it here stops it being
# mistaken for a playoff seed by the next person to read the response; the real
# seed is computed in wnba_engine/analysis/playoff_race.py.
#
# games_remaining counts scheduled games that have not gone final, which is what
# makes clinching computable at all.
#
# The last-ten form string is built here rather than shipped as ten rows: it is
# read as one token ("7-3"), and returning the games behind it would multiply
# the payload for something no client renders individually.
_STANDINGS = """
WITH schedule AS (
    SELECT t.id AS team_id,
           count(*) FILTER (WHERE g.status <> 'final')                   AS games_remaining,
           count(*) FILTER (WHERE g.status = 'final')                    AS games_played
      FROM teams t
      LEFT JOIN games g
        ON (g.home_team_id = t.id OR g.away_team_id = t.id)
       AND g.season = %(season)s
       AND g.season_type IN ('regular-season', 'post-season')
     WHERE t.is_franchise
     GROUP BY t.id
), recent AS (
    SELECT team_id,
           count(*) FILTER (WHERE won)     AS last10_wins,
           count(*) FILTER (WHERE NOT won) AS last10_losses
      FROM (
          SELECT t.id AS team_id, g.start_time,
                 CASE WHEN g.home_team_id = t.id
                      THEN g.home_score > g.away_score
                      ELSE g.away_score > g.home_score END AS won,
                 row_number() OVER (PARTITION BY t.id ORDER BY g.start_time DESC) AS rn
            FROM teams t
            JOIN games g
              ON (g.home_team_id = t.id OR g.away_team_id = t.id)
             AND g.season = %(season)s
             AND g.season_type IN ('regular-season', 'post-season')
             AND g.status = 'final'
             AND g.home_score IS NOT NULL
           WHERE t.is_franchise
      ) ranked
     WHERE rn <= 10
     GROUP BY team_id
)
SELECT t.id AS team_id, t.name, t.abbreviation, s.conference,
       s.wins, s.losses, s.win_percentage, s.games_behind,
       s.home_record, s.away_record, s.conference_record,
       s.playoff_seed AS conference_seed,
       coalesce(sc.games_remaining, 0) AS games_remaining,
       coalesce(r.last10_wins, 0)      AS last10_wins,
       coalesce(r.last10_losses, 0)    AS last10_losses
  FROM team_standings s
  JOIN teams t ON t.id = s.team_id
  LEFT JOIN schedule sc ON sc.team_id = t.id
  LEFT JOIN recent r    ON r.team_id = t.id
 WHERE s.season = %(season)s
 ORDER BY s.win_percentage DESC NULLS LAST, s.wins DESC
"""

# Shot chart, binned server-side.
#
# 30,666 shots in the 2026 season alone. Sending them raw would be a multi-MB
# payload for a chart that can only resolve a few hundred distinct positions
# anyway, so the grid is computed here where the data already is.
#
# Coordinates are the standard NBA tenths-of-a-foot system: x in [-250, 250]
# across the floor, y from the hoop at 0 toward half court. BIN_SIZE tenths per
# cell. Cells below a minimum attempt count are still returned -- the caller
# decides what is too sparse to colour, because that threshold is a display
# choice, not a data one.
#
# Cells carry POINTS, not just makes, and the chart is coloured by points per
# attempt rather than FG%. This is the difference between a correct shot chart
# and a misleading one: a 35% three is well above average and a 35% layup is
# poor, so a single FG% ramp paints the entire arc as bad. Points per attempt
# puts every location on one honest scale.
_SHOT_CHART = """
SELECT (floor(s.loc_x / %(bin)s) * %(bin)s)::int AS x,
       (floor(s.loc_y / %(bin)s) * %(bin)s)::int AS y,
       count(*)                        AS attempts,
       count(*) FILTER (WHERE s.made)  AS makes,
       sum(CASE WHEN s.made
                THEN CASE WHEN s.shot_zone_basic LIKE '%%3%%' THEN 3 ELSE 2 END
                ELSE 0 END)            AS points
  FROM shot_locations s
  JOIN games g ON g.id = s.game_id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   AND (%(player_id)s::bigint IS NULL OR s.player_id = %(player_id)s::bigint)
   AND (%(team_id)s::bigint   IS NULL OR s.team_id   = %(team_id)s::bigint)
   -- Beyond half court is a heave at the buzzer, not a shot profile.
   AND s.loc_y BETWEEN -50 AND 470
 GROUP BY 1, 2
 ORDER BY 1, 2
"""

# Shooting split by zone, which is what a shot chart is actually read for.
_SHOT_ZONES = """
SELECT s.shot_zone_basic AS zone,
       count(*)                        AS attempts,
       count(*) FILTER (WHERE s.made)  AS makes,
       round(avg(s.shot_distance)::numeric, 1) AS avg_distance
  FROM shot_locations s
  JOIN games g ON g.id = s.game_id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   AND (%(player_id)s::bigint IS NULL OR s.player_id = %(player_id)s::bigint)
   AND (%(team_id)s::bigint   IS NULL OR s.team_id   = %(team_id)s::bigint)
   AND s.shot_zone_basic IS NOT NULL
 GROUP BY 1
 ORDER BY 2 DESC
"""

# Zone splits for a whole roster in one query, not one round trip per player --
# built for the pre-game "who has a real edge tonight" matchup, which checks a
# team's rotation (5-8 players) against an opponent, and doubling that per game
# would otherwise be a dozen-plus requests for one section.
_PLAYERS_SHOT_ZONES = """
SELECT s.player_id, s.shot_zone_basic AS zone,
       count(*)                       AS attempts,
       count(*) FILTER (WHERE s.made) AS makes
  FROM shot_locations s
  JOIN games g ON g.id = s.game_id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   AND s.player_id = ANY(%(player_ids)s::bigint[])
   AND s.shot_zone_basic IS NOT NULL
 GROUP BY 1, 2
"""

# A team's shot chart windowed by RECENT GAMES rather than season -- built
# for previewing a game that hasn't been played yet, where the season-long
# profile above would silently include nothing (no shots exist for a future
# game) and a single game's shots would be too few to bin meaningfully. Games
# not yet final are excluded by construction: ordering by start_time DESC and
# taking the games table's own rows says nothing about whether shots exist yet,
# so the JOIN to shot_locations is what actually limits this to played games.
_TEAM_RECENT_GAMES = """
SELECT g.id
  FROM games g
 WHERE %(team_id)s::bigint IN (g.home_team_id, g.away_team_id)
   AND g.season_type IN ('regular-season', 'post-season')
   AND g.status = 'final'
 ORDER BY g.start_time DESC
 LIMIT %(last_n_games)s
"""

_TEAM_RECENT_SHOT_CHART = """
WITH recent_games AS (""" + _TEAM_RECENT_GAMES + """)
SELECT (floor(s.loc_x / %(bin)s) * %(bin)s)::int AS x,
       (floor(s.loc_y / %(bin)s) * %(bin)s)::int AS y,
       count(*)                        AS attempts,
       count(*) FILTER (WHERE s.made)  AS makes,
       sum(CASE WHEN s.made
                THEN CASE WHEN s.shot_zone_basic LIKE '%%3%%' THEN 3 ELSE 2 END
                ELSE 0 END)            AS points
  FROM shot_locations s
  JOIN recent_games rg ON rg.id = s.game_id
 WHERE s.team_id = %(team_id)s::bigint
   AND s.loc_y BETWEEN -50 AND 470
 GROUP BY 1, 2
 ORDER BY 1, 2
"""

_TEAM_RECENT_SHOT_ZONES = """
WITH recent_games AS (""" + _TEAM_RECENT_GAMES + """)
SELECT s.shot_zone_basic AS zone,
       count(*)                        AS attempts,
       count(*) FILTER (WHERE s.made)  AS makes,
       round(avg(s.shot_distance)::numeric, 1) AS avg_distance
  FROM shot_locations s
  JOIN recent_games rg ON rg.id = s.game_id
 WHERE s.team_id = %(team_id)s::bigint
   AND s.shot_zone_basic IS NOT NULL
 GROUP BY 1
 ORDER BY 2 DESC
"""

# Usage against efficiency -- the standard way to separate volume from value.
#
# Same DISTINCT ON guard as the leaders query, and for the same reason:
# player_advanced_stats is keyed (game_id, player_id, SOURCE).
_EFFICIENCY = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (a.player_id, a.game_id)
           a.player_id, a.game_id, a.team_id,
           a.usage_percentage, a.true_shooting_percentage,
           a.offensive_rating, a.defensive_rating, a.net_rating,
           -- `minutes` is TEXT in "MM:SS" form, not a number: this table stores
           -- the provider's own clock string. Parsed to fractional minutes here
           -- rather than averaged raw, which fails outright with
           -- "function avg(text) does not exist".
           (split_part(a.minutes, ':', 1)::numeric
            + split_part(a.minutes, ':', 2)::numeric / 60) AS minutes
      FROM player_advanced_stats a
      JOIN games g ON g.id = a.game_id
     WHERE g.season = %(season)s
        AND g.season_type IN ('regular-season', 'post-season')
       AND a.minutes ~ '^[0-9]+:[0-9]{2}$'
       AND (%(player_id)s::bigint IS NULL OR a.player_id = %(player_id)s::bigint)
     ORDER BY a.player_id, a.game_id, a.source
)
SELECT p.id AS player_id, p.full_name,
       (array_agg(t.abbreviation ORDER BY r.game_id DESC))[1] AS team_abbr,
       count(*) AS games_played,
       round(avg(r.usage_percentage)::numeric, 3)         AS usage_pct,
       round(avg(r.true_shooting_percentage)::numeric, 3) AS true_shooting,
       round(avg(r.net_rating)::numeric, 1)               AS net_rating,
       round(avg(r.minutes)::numeric, 1)                  AS minutes
  FROM one_row_per_game r
  JOIN players p ON p.id = r.player_id
  JOIN teams   t ON t.id = r.team_id
 GROUP BY p.id, p.full_name
HAVING count(*) >= %(min_games)s
   AND avg(r.usage_percentage) IS NOT NULL
   AND avg(r.true_shooting_percentage) IS NOT NULL
 ORDER BY avg(r.usage_percentage) DESC
 LIMIT %(limit)s
"""

# Score margin through a game, for a score-flow chart.
#
# `sequence` rather than the clock: `clock` is a display string that restarts
# every period, so ordering by it interleaves the quarters. Only scoring plays
# are returned -- the other ~85% of rows leave the margin unchanged and would
# quadruple the payload to draw the same staircase.
# game_plays.sequence is assigned independently PER PROVIDER (balldontlie and
# wnba_stats each number their own scoring plays from roughly 1, covering
# overlapping ranges for the same game) -- interleaving both by raw sequence
# treats two unrelated numbering systems as one timeline, which produces a
# score margin that jumps backward every time the two providers' rows
# alternate rather than climbing monotonically. Picking one provider per game
# (whichever has fuller scoring-play coverage for THIS game, tie-broken
# alphabetically for determinism) keeps sequence meaningful, the same way
# _LEADERS picks one source per player rather than averaging both.
_GAME_FLOW = """
WITH preferred_source AS (
    SELECT source
      FROM game_plays
     WHERE game_id = %(game_id)s
       AND scoring_play
       AND home_score IS NOT NULL
       AND away_score IS NOT NULL
     GROUP BY source
     ORDER BY count(*) DESC, source
     LIMIT 1
)
SELECT p.sequence, p.period, p.clock,
       p.home_score, p.away_score,
       (p.home_score - p.away_score) AS margin,
       p.description
  FROM game_plays p
 WHERE p.game_id = %(game_id)s
   AND p.scoring_play
   AND p.home_score IS NOT NULL
   AND p.away_score IS NOT NULL
   AND p.source = (SELECT source FROM preferred_source)
 ORDER BY p.sequence
"""

# Season leaders, averaged over games actually played.
#
# player_game_stats is keyed (game_id, player_id, SOURCE), and both ESPN and
# balldontlie write a row per game with different coverage -- for A'ja Wilson in
# 2026, 32 games from ESPN and 26 from balldontlie. Averaging the raw table
# therefore reports 58 "games played" for a 44-game season and silently
# double-weights whichever games both providers happen to cover.
#
# So DISTINCT ON collapses to one row per (player, game) first, preferring ESPN
# because it is the broader feed. did_not_play rows are excluded before the
# average: they carry NULL minutes and would drag every per-game figure down.
_LEADERS = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (s.player_id, s.game_id)
           s.player_id, s.game_id, s.team_id,
           s.points, s.rebounds, s.assists, s.steals, s.blocks, s.minutes
      FROM player_game_stats s
      JOIN games g ON g.id = s.game_id
     WHERE g.season = %(season)s
        AND g.season_type IN ('regular-season', 'post-season')
       AND s.did_not_play IS NOT TRUE
     ORDER BY s.player_id, s.game_id,
              CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
)
SELECT p.id AS player_id, p.full_name,
       -- Most recent team, not every team: grouping by team would split a
       -- traded player into two partial-season rows on the same board.
       (array_agg(t.abbreviation ORDER BY r.game_id DESC))[1] AS team_abbr,
       count(*)                            AS games_played,
       round(avg(r.points)::numeric, 1)    AS points,
       round(avg(r.rebounds)::numeric, 1)  AS rebounds,
       round(avg(r.assists)::numeric, 1)   AS assists,
       round(avg(r.steals)::numeric, 1)    AS steals,
       round(avg(r.blocks)::numeric, 1)    AS blocks,
       round(avg(r.minutes)::numeric, 1)   AS minutes
  FROM one_row_per_game r
  JOIN players p ON p.id = r.player_id
  JOIN teams   t ON t.id = r.team_id
 GROUP BY p.id, p.full_name
HAVING count(*) >= %(min_games)s
 ORDER BY avg(r.points) DESC NULLS LAST
 LIMIT %(limit)s
"""


def fetch_summary(conn: Connection) -> dict[str, Any]:
    return _one(conn, _SUMMARY, {}) or {}


def fetch_recent_games(
    conn: Connection, *, season: int | None, since: date | None, limit: int
) -> list[dict[str, Any]]:
    return _all(conn, _RECENT_GAMES, {"season": season, "since": since, "limit": _cap(limit)})


def fetch_game(conn: Connection, game_id: int) -> dict[str, Any] | None:
    return _one(conn, _GAME_BY_ID, {"game_id": game_id})


def fetch_game_odds_history(conn: Connection, game_id: int, *, limit: int) -> list[dict[str, Any]]:
    return _all(conn, _GAME_ODDS_HISTORY, {"game_id": game_id, "limit": _cap(limit)})


def fetch_game_market_prices(conn: Connection, game_id: int, *, limit: int) -> list[dict[str, Any]]:
    return _all(
        conn,
        _GAME_MARKET_PRICES,
        {
            "game_id": game_id,
            "limit": _cap(limit),
            "kalshi_prefix": f"{KALSHI_GAME_SERIES_PREFIX}%",
        },
    )


def fetch_divergences(
    conn: Connection, *, venue: str | None, graded_only: bool, limit: int
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _DIVERGENCES,
        {"venue": venue, "graded_only": graded_only, "limit": _cap(limit)},
    )


def fetch_divergence_summary(conn: Connection) -> list[dict[str, Any]]:
    return _all(conn, _DIVERGENCE_SUMMARY, {})


def fetch_leaders(
    conn: Connection, *, season: int, min_games: int, limit: int
) -> list[dict[str, Any]]:
    return _all(
        conn, _LEADERS, {"season": season, "min_games": min_games, "limit": _cap(limit)}
    )


def fetch_standings(conn: Connection, *, season: int) -> list[dict[str, Any]]:
    return _all(conn, _STANDINGS, {"season": season})


def fetch_shot_chart(
    conn: Connection, *, season: int, player_id: int | None, team_id: int | None, bin_size: int
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _SHOT_CHART,
        {"season": season, "player_id": player_id, "team_id": team_id, "bin": bin_size},
    )


def fetch_shot_zones(
    conn: Connection, *, season: int, player_id: int | None, team_id: int | None
) -> list[dict[str, Any]]:
    return _all(
        conn, _SHOT_ZONES, {"season": season, "player_id": player_id, "team_id": team_id}
    )


def fetch_players_shot_zones(
    conn: Connection, *, player_ids: list[int], season: int
) -> list[dict[str, Any]]:
    if not player_ids:
        return []
    return _all(conn, _PLAYERS_SHOT_ZONES, {"player_ids": player_ids, "season": season})


def fetch_team_recent_shot_chart(
    conn: Connection, *, team_id: int, last_n_games: int, bin_size: int
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _TEAM_RECENT_SHOT_CHART,
        {"team_id": team_id, "last_n_games": last_n_games, "bin": bin_size},
    )


def fetch_team_recent_shot_zones(
    conn: Connection, *, team_id: int, last_n_games: int
) -> list[dict[str, Any]]:
    return _all(
        conn, _TEAM_RECENT_SHOT_ZONES, {"team_id": team_id, "last_n_games": last_n_games}
    )


def fetch_team_recent_game_ids(
    conn: Connection, *, team_id: int, last_n_games: int
) -> list[int]:
    """How many of the requested games actually exist -- early in a season,
    "last 10" may only find 4, and the response should say so rather than
    implying a full window."""
    rows = _all(conn, _TEAM_RECENT_GAMES, {"team_id": team_id, "last_n_games": last_n_games})
    return [int(row["id"]) for row in rows]


def fetch_efficiency(
    conn: Connection, *, season: int, min_games: int, limit: int, player_id: int | None = None
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _EFFICIENCY,
        {
            "season": season,
            "min_games": min_games,
            "limit": _cap(limit),
            "player_id": player_id,
        },
    )


def fetch_game_flow(conn: Connection, game_id: int) -> list[dict[str, Any]]:
    return _all(conn, _GAME_FLOW, {"game_id": game_id})


def _cap(limit: int) -> int:
    return max(1, min(limit, MAX_ROWS))


def _all(conn: Connection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [description.name for description in cursor.description or ()]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _one(conn: Connection, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    rows = _all(conn, sql, params)
    return rows[0] if rows else None


# Entities that have an ESPN id, which is what an image URL is built from.
# INNER JOIN on the crosswalk: a player with no mapping has no image to fetch,
# and returning them would only produce 404s to count.
_IMAGE_TARGETS_PLAYERS = """
SELECT p.id AS internal_id, m.external_id, p.full_name AS label
  FROM players p
  JOIN provider_entity_map m
    ON m.internal_id = p.id AND m.provider = 'espn' AND m.entity_type = 'player'
 ORDER BY p.id
"""

_IMAGE_TARGETS_TEAMS = """
SELECT t.id AS internal_id, t.abbreviation AS external_id, t.name AS label
  FROM teams t
 WHERE t.abbreviation IS NOT NULL
 ORDER BY t.id
"""


def fetch_player_image_targets(conn: Connection) -> list[dict[str, Any]]:
    return _all(conn, _IMAGE_TARGETS_PLAYERS, {})


def fetch_team_image_targets(conn: Connection) -> list[dict[str, Any]]:
    return _all(conn, _IMAGE_TARGETS_TEAMS, {})


# --------------------------------------------------------------------- teams
_TEAMS = """
SELECT t.id, t.name, t.abbreviation, t.is_franchise,
       s.conference, s.wins, s.losses, s.win_percentage,
       s.playoff_seed AS conference_seed
  FROM teams t
  LEFT JOIN team_standings s ON s.team_id = t.id AND s.season = %(season)s
 WHERE t.is_franchise
 ORDER BY s.win_percentage DESC NULLS LAST, t.name
"""

_TEAM_BY_ID = """
SELECT t.id, t.name, t.abbreviation, t.is_franchise,
       s.conference, s.wins, s.losses, s.win_percentage, s.games_behind,
       s.home_record, s.away_record, s.playoff_seed AS conference_seed
  FROM teams t
  LEFT JOIN team_standings s ON s.team_id = t.id AND s.season = %(season)s
 WHERE t.id = %(team_id)s
"""

# Roster for a season, built from who actually played rather than from a roster
# feed we do not ingest. Ordered by minutes, so the rotation reads top to bottom.
_TEAM_ROSTER = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (s.player_id, s.game_id)
           s.player_id, s.game_id, s.team_id, s.points, s.rebounds,
           s.assists, s.steals, s.blocks, s.minutes
      FROM player_game_stats s
      JOIN games g ON g.id = s.game_id
     WHERE g.season = %(season)s
        AND g.season_type IN ('regular-season', 'post-season')
       AND s.team_id = %(team_id)s
       AND s.did_not_play IS NOT TRUE
     ORDER BY s.player_id, s.game_id,
              CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
)
SELECT p.id AS player_id, p.full_name, p.position, p.jersey_number,
       count(*)                           AS games_played,
       round(avg(r.points)::numeric, 1)   AS points,
       round(avg(r.rebounds)::numeric, 1) AS rebounds,
       round(avg(r.assists)::numeric, 1)  AS assists,
       round(avg(r.steals)::numeric, 1)   AS steals,
       round(avg(r.blocks)::numeric, 1)   AS blocks,
       round(avg(r.minutes)::numeric, 1)  AS minutes
  FROM one_row_per_game r
  JOIN players p ON p.id = r.player_id
 GROUP BY p.id, p.full_name, p.position, p.jersey_number
 ORDER BY avg(r.minutes) DESC NULLS LAST
"""

# Schedule with the closing number each game was played to.
#
# The line is reported from THIS team's perspective, not the home team's: a
# schedule that shows a home spread on every row makes the reader flip the sign
# on half of them, and getting that wrong silently inverts the result.
#
# Consensus is built per book first (each book's last quote before tip), for the
# reason spelled out in wnba_engine/repositories/betting_repo.py -- averaging
# raw rows weights whichever book repriced most often.
_TEAM_SCHEDULE = """
WITH per_vendor AS (
    SELECT DISTINCT ON (o.game_id, o.vendor)
           o.game_id, o.spread_home_value, o.total_value
      FROM sportsbook_game_odds o
      JOIN games g ON g.id = o.game_id
     WHERE o.captured_at <= g.start_time
       AND g.season = %(season)s
       AND g.season_type IN ('regular-season', 'post-season')
       AND (g.home_team_id = %(team_id)s OR g.away_team_id = %(team_id)s)
     ORDER BY o.game_id, o.vendor, o.captured_at DESC
), consensus AS (
    SELECT game_id,
           avg(spread_home_value) AS spread_home,
           avg(total_value)       AS total,
           count(*)               AS books
      FROM per_vendor
     GROUP BY game_id
)
SELECT g.id, g.start_time, g.status, g.home_score, g.away_score,
       (g.home_team_id = %(team_id)s) AS is_home,
       opp.id AS opponent_id, opp.name AS opponent, opp.abbreviation AS opponent_abbr,
       c.books,
       round((CASE WHEN g.home_team_id = %(team_id)s
                   THEN c.spread_home ELSE -c.spread_home END)::numeric, 1) AS spread,
       round(c.total::numeric, 1) AS total,
       CASE
         WHEN g.status <> 'final' OR c.spread_home IS NULL THEN NULL
         WHEN g.home_team_id = %(team_id)s
              THEN CASE WHEN (g.home_score - g.away_score) + c.spread_home > 0 THEN TRUE
                        WHEN (g.home_score - g.away_score) + c.spread_home < 0 THEN FALSE END
         ELSE CASE WHEN (g.away_score - g.home_score) - c.spread_home > 0 THEN TRUE
                   WHEN (g.away_score - g.home_score) - c.spread_home < 0 THEN FALSE END
       END AS covered,
       CASE
         WHEN g.status <> 'final' OR c.total IS NULL THEN NULL
         WHEN (g.home_score + g.away_score) > c.total THEN TRUE
         WHEN (g.home_score + g.away_score) < c.total THEN FALSE
       END AS went_over
  FROM games g
  JOIN teams opp
    ON opp.id = CASE WHEN g.home_team_id = %(team_id)s
                     THEN g.away_team_id ELSE g.home_team_id END
  LEFT JOIN consensus c ON c.game_id = g.id
 WHERE g.season = %(season)s
    AND g.season_type IN ('regular-season', 'post-season')
   AND (g.home_team_id = %(team_id)s OR g.away_team_id = %(team_id)s)
 ORDER BY g.start_time DESC
"""

# ------------------------------------------------------------------- players
# `has_image` starts from the crosswalk rather than asking object storage per
# row: the mirror only fetches players with an ESPN id, so that mapping is
# most of what determines whether an image can exist. It isn't all of it --
# an id existing doesn't mean ESPN's own resizer actually has a photo behind
# it, so `headshot_unavailable` (set by a one-time backfill migration; see
# 0037) excludes the known cases where it doesn't.
_PLAYERS = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (s.player_id, s.game_id)
           s.player_id, s.game_id, s.team_id, s.points, s.minutes,
           s.rebounds, s.assists, s.steals, s.blocks
      FROM player_game_stats s
      JOIN games g ON g.id = s.game_id
     WHERE g.season = %(season)s
        AND g.season_type IN ('regular-season', 'post-season')
       AND s.did_not_play IS NOT TRUE
     ORDER BY s.player_id, s.game_id,
              CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
)
SELECT p.id AS player_id, p.full_name, p.position,
       (array_agg(t.abbreviation ORDER BY r.game_id DESC))[1] AS team_abbr,
       (array_agg(t.id           ORDER BY r.game_id DESC))[1] AS team_id,
       count(*)                            AS games_played,
       round(avg(r.points)::numeric, 1)    AS points,
       round(avg(r.minutes)::numeric, 1)   AS minutes,
       round(avg(r.rebounds)::numeric, 1)  AS rebounds,
       round(avg(r.assists)::numeric, 1)   AS assists,
       round(avg(r.steals)::numeric, 1)    AS steals,
       round(avg(r.blocks)::numeric, 1)    AS blocks,
       (EXISTS (SELECT 1 FROM provider_entity_map m
                 WHERE m.internal_id = p.id AND m.provider = 'espn'
                   AND m.entity_type = 'player')
        AND NOT p.headshot_unavailable) AS has_image
  FROM one_row_per_game r
  JOIN players p ON p.id = r.player_id
  JOIN teams   t ON t.id = r.team_id
 WHERE (%(query)s::text IS NULL OR p.full_name ILIKE '%%' || %(query)s::text || '%%')
 GROUP BY p.id, p.full_name, p.position
 ORDER BY avg(r.points) DESC NULLS LAST
 LIMIT %(limit)s
"""

_PLAYER_BY_ID = """
SELECT p.id AS player_id, p.full_name, p.position, p.height, p.weight,
       p.jersey_number, p.college, p.age,
       (EXISTS (SELECT 1 FROM provider_entity_map m
                 WHERE m.internal_id = p.id AND m.provider = 'espn'
                   AND m.entity_type = 'player')
        AND NOT p.headshot_unavailable) AS has_image
  FROM players p
 WHERE p.id = %(player_id)s
"""

# Per-season averages, so a profile shows a career arc rather than one row.
_PLAYER_SEASONS = """
WITH one_row_per_game AS (
    SELECT DISTINCT ON (s.player_id, s.game_id)
           s.player_id, s.game_id, s.team_id, g.season,
           s.points, s.rebounds, s.assists, s.steals, s.blocks, s.minutes,
           s.field_goals_made, s.field_goals_attempted,
           s.three_pointers_made, s.three_pointers_attempted
      FROM player_game_stats s
      JOIN games g ON g.id = s.game_id
     WHERE s.player_id = %(player_id)s
       AND s.did_not_play IS NOT TRUE
       -- Missed in the original cut (commit 1e7b3ed fixed every sibling
       -- query in this file, this one included season 2026's All-Star Game
       -- and preseason exhibitions in a player's own "season" averages.
       AND g.season_type IN ('regular-season', 'post-season')
     ORDER BY s.player_id, s.game_id,
              CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
)
SELECT r.season,
       (array_agg(t.abbreviation ORDER BY r.game_id DESC))[1] AS team_abbr,
       (array_agg(t.id ORDER BY r.game_id DESC))[1]           AS team_id,
       count(*)                            AS games_played,
       round(avg(r.points)::numeric, 1)    AS points,
       round(avg(r.rebounds)::numeric, 1)  AS rebounds,
       round(avg(r.assists)::numeric, 1)   AS assists,
       round(avg(r.steals)::numeric, 1)    AS steals,
       round(avg(r.blocks)::numeric, 1)    AS blocks,
       round(avg(r.minutes)::numeric, 1)   AS minutes,
       CASE WHEN sum(r.field_goals_attempted) > 0
            THEN round((sum(r.field_goals_made)::numeric
                        / sum(r.field_goals_attempted)), 3) END AS field_goal_pct,
       CASE WHEN sum(r.three_pointers_attempted) > 0
            THEN round((sum(r.three_pointers_made)::numeric
                        / sum(r.three_pointers_attempted)), 3) END AS three_point_pct
  FROM one_row_per_game r
  JOIN teams t ON t.id = r.team_id
 GROUP BY r.season
 ORDER BY r.season DESC
"""

_PLAYER_GAME_LOG = """
SELECT DISTINCT ON (g.id)
       g.id AS game_id, g.start_time, g.status, g.season,
       s.points, s.rebounds, s.assists, s.steals, s.blocks, s.turnovers,
       s.minutes, s.field_goals_made, s.field_goals_attempted,
       s.three_pointers_made, s.three_pointers_attempted, s.plus_minus,
       opp.abbreviation AS opponent_abbr, opp.id AS opponent_id,
       (g.home_team_id = s.team_id) AS is_home,
       g.home_score, g.away_score
  FROM player_game_stats s
  JOIN games g ON g.id = s.game_id
  JOIN teams opp
    ON opp.id = CASE WHEN g.home_team_id = s.team_id
                     THEN g.away_team_id ELSE g.home_team_id END
 WHERE s.player_id = %(player_id)s
   AND (%(season)s::int IS NULL OR g.season = %(season)s::int)
   AND g.season_type IN ('regular-season', 'post-season')
   AND s.did_not_play IS NOT TRUE
 ORDER BY g.id DESC,
          CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
"""

_GAME_BOX_SCORE = """
SELECT DISTINCT ON (s.player_id)
       s.player_id, p.full_name, s.team_id, t.abbreviation AS team_abbr,
       s.starter, s.minutes, s.points, s.rebounds, s.assists, s.steals,
       s.blocks, s.turnovers, s.fouls, s.plus_minus,
       s.field_goals_made, s.field_goals_attempted,
       s.three_pointers_made, s.three_pointers_attempted,
       s.free_throws_made, s.free_throws_attempted
  FROM player_game_stats s
  JOIN players p ON p.id = s.player_id
  JOIN teams   t ON t.id = s.team_id
 WHERE s.game_id = %(game_id)s
   AND s.did_not_play IS NOT TRUE
 ORDER BY s.player_id,
          CASE s.source WHEN 'espn' THEN 0 WHEN 'balldontlie' THEN 1 ELSE 2 END
"""


def fetch_teams(conn: Connection, *, season: int) -> list[dict[str, Any]]:
    return _all(conn, _TEAMS, {"season": season})


def fetch_team(conn: Connection, team_id: int, *, season: int) -> dict[str, Any] | None:
    return _one(conn, _TEAM_BY_ID, {"team_id": team_id, "season": season})


def fetch_team_roster(conn: Connection, team_id: int, *, season: int) -> list[dict[str, Any]]:
    return _all(conn, _TEAM_ROSTER, {"team_id": team_id, "season": season})


def fetch_team_schedule(conn: Connection, team_id: int, *, season: int) -> list[dict[str, Any]]:
    return _all(conn, _TEAM_SCHEDULE, {"team_id": team_id, "season": season})


def fetch_players(
    conn: Connection, *, season: int, query: str | None, limit: int
) -> list[dict[str, Any]]:
    return _all(conn, _PLAYERS, {"season": season, "query": query, "limit": _cap(limit)})


def fetch_player(conn: Connection, player_id: int) -> dict[str, Any] | None:
    return _one(conn, _PLAYER_BY_ID, {"player_id": player_id})


def fetch_player_seasons(conn: Connection, player_id: int) -> list[dict[str, Any]]:
    return _all(conn, _PLAYER_SEASONS, {"player_id": player_id})


def fetch_player_game_log(
    conn: Connection, player_id: int, *, season: int | None
) -> list[dict[str, Any]]:
    return _all(conn, _PLAYER_GAME_LOG, {"player_id": player_id, "season": season})


def fetch_game_box_score(conn: Connection, game_id: int) -> list[dict[str, Any]]:
    return _all(conn, _GAME_BOX_SCORE, {"game_id": game_id})
