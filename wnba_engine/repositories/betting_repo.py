"""Sportsbook line data: closing lines, line movement, and results against them.

Split out of analytics_repo because that file had grown past the point where the
next reader could hold it, and because these queries share one non-obvious
problem worth explaining once.

**Consensus, not "the line".** There is no such thing as the line: eight-plus
books price every game and they disagree. Every query here therefore reduces to
one row per vendor first -- the last quote each book published before tip -- and
only then averages across books. Skipping the first step weights a book that
posted forty times more heavily than one that posted twice, which quietly turns
a consensus into "whoever repriced most often".

**Closing means before tip.** `captured_at <= start_time` is load-bearing. The
odds feed keeps returning rows during and after a game, and including them lets
the result leak into the line -- a backtest built on that would look brilliant
and be worthless. This is the same point-in-time discipline the feature layer
enforces (wnba_engine/features/).
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from wnba_engine.repositories.analytics_repo import MAX_ROWS, _all, _cap, _one

# One row per (game, vendor): that book's last quote before tip-off.
_LAST_QUOTE_BEFORE_TIP = """
    SELECT DISTINCT ON (o.game_id, o.vendor)
           o.game_id, o.vendor, o.captured_at,
           o.spread_home_value, o.spread_home_odds,
           o.total_value, o.total_over_odds, o.total_under_odds,
           o.moneyline_home_odds, o.moneyline_away_odds
      FROM sportsbook_game_odds o
      JOIN games g ON g.id = o.game_id
     WHERE o.captured_at <= g.start_time
       AND ({game_filter})
     ORDER BY o.game_id, o.vendor, o.captured_at DESC
"""

# Consensus closing line for a set of games, plus how the game finished against
# it. `covered` is NULL for a push and for anything not yet final -- a push is
# not a loss and must not be counted as one.
_CLOSING_LINES = f"""
WITH per_vendor AS (
{_LAST_QUOTE_BEFORE_TIP.format(game_filter="o.game_id = ANY(%(game_ids)s)")}
), consensus AS (
    SELECT game_id,
           round(avg(spread_home_value)::numeric, 1) AS spread_home,
           round(avg(total_value)::numeric, 1)       AS total,
           round(avg(moneyline_home_odds)::numeric)  AS moneyline_home,
           round(avg(moneyline_away_odds)::numeric)  AS moneyline_away,
           count(*)                                  AS books,
           max(captured_at)                          AS closed_at
      FROM per_vendor
     GROUP BY game_id
)
SELECT c.*,
       g.home_score, g.away_score, g.status,
       CASE WHEN g.status <> 'final' OR c.spread_home IS NULL THEN NULL
            WHEN (g.home_score - g.away_score) + c.spread_home > 0 THEN TRUE
            WHEN (g.home_score - g.away_score) + c.spread_home < 0 THEN FALSE
       END AS home_covered,
       CASE WHEN g.status <> 'final' OR c.total IS NULL THEN NULL
            WHEN (g.home_score + g.away_score) > c.total THEN TRUE
            WHEN (g.home_score + g.away_score) < c.total THEN FALSE
       END AS went_over
  FROM consensus c
  JOIN games g ON g.id = c.game_id
"""

# Full movement for one game, one point per (vendor, capture). The UI averages
# across vendors per timestamp; returning it un-aggregated keeps the option of
# showing book disagreement, which is the whole subject of the divergence work.
_LINE_MOVEMENT = """
SELECT vendor, captured_at,
       spread_home_value, spread_home_odds,
       total_value, total_over_odds, total_under_odds,
       moneyline_home_odds, moneyline_away_odds
  FROM sportsbook_game_odds
 WHERE game_id = %(game_id)s
 ORDER BY captured_at
 LIMIT %(limit)s
"""

# A team's record against the closing spread and total.
#
# Pushes are excluded from both the numerator and the denominator: a 3-point
# favourite winning by exactly 3 neither covered nor failed to, and counting it
# either way biases every rate reported here.
_TEAM_BETTING_RECORD = f"""
WITH per_vendor AS (
{_LAST_QUOTE_BEFORE_TIP.format(
    game_filter="g.home_team_id = %(team_id)s OR g.away_team_id = %(team_id)s"
)}
), consensus AS (
    SELECT game_id,
           avg(spread_home_value) AS spread_home,
           avg(total_value)       AS total
      FROM per_vendor
     GROUP BY game_id
), graded AS (
    SELECT g.id,
           (g.home_team_id = %(team_id)s) AS is_home,
           c.spread_home, c.total,
           (g.home_score - g.away_score) AS home_margin,
           (g.home_score + g.away_score) AS combined
      FROM consensus c
      JOIN games g ON g.id = c.game_id
     WHERE g.season = %(season)s
       AND g.status = 'final'
       AND g.home_score IS NOT NULL
)
SELECT
    count(*) FILTER (WHERE spread_home IS NOT NULL)                       AS spread_games,
    count(*) FILTER (WHERE spread_home IS NOT NULL
                       AND ((is_home AND home_margin + spread_home > 0)
                         OR (NOT is_home AND -home_margin - spread_home > 0)))  AS covers,
    count(*) FILTER (WHERE spread_home IS NOT NULL
                       AND ((is_home AND home_margin + spread_home < 0)
                         OR (NOT is_home AND -home_margin - spread_home < 0)))  AS non_covers,
    count(*) FILTER (WHERE total IS NOT NULL AND combined > total)        AS overs,
    count(*) FILTER (WHERE total IS NOT NULL AND combined < total)        AS unders,
    round(avg(total)::numeric, 1)                                         AS avg_total,
    round(avg(CASE WHEN is_home THEN spread_home ELSE -spread_home END)::numeric, 1)
                                                                          AS avg_spread
  FROM graded
"""

# Player prop lines against what actually happened.
#
# analysis_prop_closing holds one row per VENDOR, so a raw average over it
# weights a game covered by six books six times. Reduced to one consensus line
# per (game, prop) first.
#
# Pushes -- realized exactly equal to the line -- are excluded from the over
# rate for the same reason as spread pushes. Whole-number lines make this
# common, not theoretical.
_PLAYER_PROP_SUMMARY = """
WITH per_game AS (
    SELECT game_id, prop_type,
           avg(line_value) AS line,
           max(realized)   AS realized
      FROM analysis_prop_closing
     WHERE player_id = %(player_id)s
       AND realized IS NOT NULL
       AND (%(season)s::int IS NULL
            OR date_part('year', start_time) = %(season)s::int)
     GROUP BY game_id, prop_type
)
SELECT prop_type,
       count(*)                                              AS games,
       round(avg(line)::numeric, 1)                          AS avg_line,
       round(avg(realized)::numeric, 1)                      AS avg_realized,
       count(*) FILTER (WHERE realized > line)                AS overs,
       count(*) FILTER (WHERE realized < line)                AS unders,
       count(*) FILTER (WHERE realized = line)                AS pushes
  FROM per_game
 GROUP BY prop_type
 ORDER BY count(*) DESC
"""

_PLAYER_PROP_LOG = """
WITH per_game AS (
    SELECT c.game_id, c.prop_type, c.start_time,
           avg(c.line_value) AS line,
           max(c.realized)   AS realized,
           count(DISTINCT c.vendor) AS books
      FROM analysis_prop_closing c
     WHERE c.player_id = %(player_id)s
       AND c.prop_type = %(prop_type)s
       AND c.realized IS NOT NULL
     GROUP BY c.game_id, c.prop_type, c.start_time
)
SELECT p.game_id, p.start_time, p.books,
       round(p.line::numeric, 1) AS line,
       p.realized,
       CASE WHEN p.realized > p.line THEN 'over'
            WHEN p.realized < p.line THEN 'under'
            ELSE 'push' END AS result,
       opp.abbreviation AS opponent_abbr, opp.id AS opponent_id
  FROM per_game p
  JOIN games g ON g.id = p.game_id
  JOIN player_game_stats s
    ON s.game_id = g.id AND s.player_id = %(player_id)s AND s.source = 'espn'
  JOIN teams opp
    ON opp.id = CASE WHEN g.home_team_id = s.team_id THEN g.away_team_id ELSE g.home_team_id END
 ORDER BY p.start_time DESC
 LIMIT %(limit)s
"""

# League-wide over rate per prop type. The headline number for the unders bias,
# reported with its denominator.
_PROP_MARKET_SUMMARY = """
WITH per_game AS (
    SELECT game_id, player_id, prop_type,
           avg(line_value) AS line,
           max(realized)   AS realized
      FROM analysis_prop_closing
     WHERE realized IS NOT NULL
       AND (%(season)s::int IS NULL
            OR date_part('year', start_time) = %(season)s::int)
     GROUP BY game_id, player_id, prop_type
)
SELECT prop_type,
       count(*)                                AS games,
       count(*) FILTER (WHERE realized > line) AS overs,
       count(*) FILTER (WHERE realized < line) AS unders,
       count(*) FILTER (WHERE realized = line) AS pushes,
       round(avg(line)::numeric, 2)            AS avg_line
  FROM per_game
 GROUP BY prop_type
 ORDER BY count(*) DESC
"""


def fetch_closing_lines(conn: Connection, game_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Consensus closing line per game, keyed by game id for easy joining."""
    if not game_ids:
        return {}
    rows = _all(conn, _CLOSING_LINES, {"game_ids": game_ids[:MAX_ROWS]})
    return {int(row["game_id"]): row for row in rows}


def fetch_line_movement(conn: Connection, game_id: int, *, limit: int) -> list[dict[str, Any]]:
    return _all(conn, _LINE_MOVEMENT, {"game_id": game_id, "limit": _cap(limit)})


def fetch_team_betting_record(
    conn: Connection, team_id: int, *, season: int
) -> dict[str, Any] | None:
    return _one(conn, _TEAM_BETTING_RECORD, {"team_id": team_id, "season": season})


def fetch_player_prop_summary(
    conn: Connection, player_id: int, *, season: int | None
) -> list[dict[str, Any]]:
    return _all(conn, _PLAYER_PROP_SUMMARY, {"player_id": player_id, "season": season})


def fetch_player_prop_log(
    conn: Connection, player_id: int, *, prop_type: str, limit: int
) -> list[dict[str, Any]]:
    return _all(
        conn,
        _PLAYER_PROP_LOG,
        {"player_id": player_id, "prop_type": prop_type, "limit": _cap(limit)},
    )


def fetch_prop_market_summary(conn: Connection, *, season: int | None) -> list[dict[str, Any]]:
    return _all(conn, _PROP_MARKET_SUMMARY, {"season": season})


# --------------------------------------------------- prediction-market props
#
# Kalshi and Polymarket both list player props, and unlike the sportsbook feed
# they are FREE, unmetered, and still arriving -- captured every 30 minutes.
# They were sitting unused in market_price_snapshots while the site reported
# "no props" from a paid feed whose key lapsed on 2026-08-03.
#
# The two venues express a prop differently and both are parsed to one shape:
#
#   Kalshi      title "Rhyne Howard: 15+ points"        -> threshold market.
#               "15+" means 15 or more, so the equivalent line is 14.5 and the
#               price is the probability of going OVER it.
#   Polymarket  outcome "Aliyah Boston: Assists O/U 3.5" -> the line is stated.
#
# Only ONE quote per market is returned, and which one matters.
#
# For a game that has started, it is the last quote BEFORE tip -- the closing
# price, the same discipline the sportsbook queries use. Taking the newest quote
# instead returns the settled price: once a game is final every prop has
# resolved, so the table reads 0%, 100%, 100%, 0%. That is not the market's
# opinion of anything, it is the answer written down after the fact, and
# presenting it as a price is the sort of thing that quietly turns a research
# tool into a lie. For an upcoming game there is no tip yet, so it is simply the
# newest quote.
_MARKET_PROPS_SQL = """
WITH parsed AS (
    SELECT DISTINCT ON (s.provider, s.market_external_id)
           s.provider, s.market_external_id, s.player_id, s.game_id,
           s.implied_probability, s.volume, s.captured_at, s.status, s.title,
           CASE WHEN s.provider = 'kalshi'
                THEN lower(substring(s.title from ':\\s*\\d+\\+\\s*(\\w+)'))
                ELSE lower(substring(s.outcome from ':\\s*(\\w+)\\s+O/U'))
           END AS prop_type,
           CASE WHEN s.provider = 'kalshi'
                -- "15+" is 15 or more; the comparable line is 14.5.
                THEN substring(s.title from ':\\s*(\\d+)\\+')::numeric - 0.5
                ELSE substring(s.outcome from 'O/U\\s*([0-9.]+)')::numeric
           END AS line
      FROM market_price_snapshots s
      LEFT JOIN games gm ON gm.id = s.game_id
     WHERE s.player_id IS NOT NULL
       AND s.implied_probability IS NOT NULL
       AND (%(player_id)s::bigint IS NULL OR s.player_id = %(player_id)s::bigint)
       AND (%(game_id)s::bigint   IS NULL OR s.game_id   = %(game_id)s::bigint)
       AND (%(since)s::timestamptz IS NULL OR s.captured_at >= %(since)s::timestamptz)
       -- Closing price for a game already under way; current price otherwise.
       AND s.captured_at <= coalesce(gm.start_time, now())
     ORDER BY s.provider, s.market_external_id, s.captured_at DESC
)
SELECT p.provider, p.player_id, pl.full_name, p.game_id, p.prop_type, p.line,
       p.implied_probability AS over_probability,
       p.volume, p.captured_at, p.status, p.title,
       g.start_time, g.status AS game_status,
       home.abbreviation AS home_abbr, away.abbreviation AS away_abbr
  FROM parsed p
  JOIN players pl ON pl.id = p.player_id
  LEFT JOIN games g    ON g.id = p.game_id
  LEFT JOIN teams home ON home.id = g.home_team_id
  LEFT JOIN teams away ON away.id = g.away_team_id
 WHERE p.prop_type IS NOT NULL
   AND p.line IS NOT NULL
 ORDER BY p.captured_at DESC, pl.full_name, p.prop_type, p.line
 LIMIT %(limit)s
"""


def fetch_market_props(
    conn: Connection,
    *,
    player_id: int | None = None,
    game_id: int | None = None,
    since: str | None = None,
    limit: int = MAX_ROWS,
) -> list[dict[str, Any]]:
    """Live player props from the prediction markets, latest quote per market."""
    return _all(
        conn,
        _MARKET_PROPS_SQL,
        {
            "player_id": player_id,
            "game_id": game_id,
            "since": since,
            "limit": _cap(limit),
        },
    )
