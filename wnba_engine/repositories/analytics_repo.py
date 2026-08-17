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

# League standings.
_STANDINGS = """
SELECT t.id AS team_id, t.name, t.abbreviation, s.conference,
       s.wins, s.losses, s.win_percentage, s.games_behind,
       s.home_record, s.away_record, s.playoff_seed
  FROM team_standings s
  JOIN teams t ON t.id = s.team_id
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
   AND (%(player_id)s::bigint IS NULL OR s.player_id = %(player_id)s::bigint)
   AND (%(team_id)s::bigint   IS NULL OR s.team_id   = %(team_id)s::bigint)
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
       AND a.minutes ~ '^[0-9]+:[0-9]{2}$'
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
_GAME_FLOW = """
SELECT DISTINCT ON (p.sequence)
       p.sequence, p.period, p.clock,
       p.home_score, p.away_score,
       (p.home_score - p.away_score) AS margin,
       p.description
  FROM game_plays p
 WHERE p.game_id = %(game_id)s
   AND p.scoring_play
   AND p.home_score IS NOT NULL
   AND p.away_score IS NOT NULL
 ORDER BY p.sequence, p.source
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


def fetch_efficiency(
    conn: Connection, *, season: int, min_games: int, limit: int
) -> list[dict[str, Any]]:
    return _all(
        conn, _EFFICIENCY, {"season": season, "min_games": min_games, "limit": _cap(limit)}
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
