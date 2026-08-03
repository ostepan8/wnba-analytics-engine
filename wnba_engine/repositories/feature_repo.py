"""Read-only, point-in-time-filtered reads for the feature layer.

Nothing here writes. Every query is `WHERE <timestamp> <= %(as_of)s`, and
two module-level guards make that structural rather than customary:

- `execute_point_in_time` REFUSES any SQL that does not reference the
  `%(as_of)s` parameter. Forgetting the filter is the single most likely
  way to leak, and it is invisible in review because the query still
  returns plausible rows.
- Both helpers refuse SQL naming a known-leaky table or column. The
  refusals are keyed to specific, documented facts about THIS database
  (see `_FORBIDDEN_IDENTIFIERS`), not to a general suspicion.

Why an identifier scan rather than trusting the author: the traps below
are not obvious from the schema. `team_standings` looks like exactly the
table you want for a 2023 game and is the wrong one; `players.age` looks
immutable and is not. A reviewer who has not read DATA_INVENTORY.md end
to end will approve either. The scan is crude -- it is text matching, and
a determined author can defeat it with a view or dynamic SQL -- but it
converts the failure mode from "silently wrong model" to "loud error at
the moment you write the query".
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from psycopg import Connection
from psycopg.rows import dict_row

from wnba_engine.features.errors import LeakageError

Row = dict[str, object]

#: Identifiers this layer must never read, with the reason. Each one is a
#: fact verified against this database and recorded in DATA_INVENTORY.md.
_FORBIDDEN_IDENTIFIERS: Mapping[str, str] = {
    "team_standings": (
        "team_standings is a CURRENT-STATE UPSERT (db/migrations/0013_standings.sql: "
        "'re-fetching gives the standings as of right now'), so reading it for a 2023 "
        "game returns 2026 standings. Use team_standings_history, which is append-only "
        "and carries captured_at."
    ),
    "season_awards": (
        "season_awards is end-of-season ground truth, researched after the fact "
        "(DATA_INVENTORY.md, 'Manually curated reference data'). It is an outcome to "
        "predict or grade against, never an input feature."
    ),
    "age": (
        "players.age is a mutable snapshot 'refreshed on every re-ingestion' "
        "(DATA_INVENTORY.md), so it describes the player today, not on game day. "
        "height/weight/college are the effectively-permanent bio fields."
    ),
    "jersey_number": (
        "players.jersey_number is mutable for the same reason as players.age."
    ),
}

_AS_OF_PARAM = "%(as_of)s"

_IDENTIFIER_PATTERNS: Mapping[str, re.Pattern[str]] = {
    # \b will not fire inside team_standings_history, because the character
    # after "standings" there is an underscore -- a word character. That is
    # exactly the discrimination this needs: forbid the upsert table, allow
    # its append-only companion.
    name: re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    for name in _FORBIDDEN_IDENTIFIERS
}


class ForbiddenSourceError(LeakageError):
    """A feature query referenced a source that cannot be read point-in-time.

    Subclasses LeakageError because that is what it is -- caught early,
    at the query, instead of late, at the row.
    """

    def __init__(self, identifier: str, reason: str) -> None:
        self.identifier = identifier
        # Deliberately bypasses LeakageError.__init__: there is no row and
        # no observed timestamp here, only a query that must not run.
        Exception.__init__(
            self,
            f"feature SQL references {identifier!r}, which is not point-in-time "
            f"safe. {reason}",
        )


def _reject_forbidden_identifiers(sql: str) -> None:
    for name, pattern in _IDENTIFIER_PATTERNS.items():
        if pattern.search(sql):
            raise ForbiddenSourceError(name, _FORBIDDEN_IDENTIFIERS[name])


def execute_point_in_time(
    conn: Connection, sql: str, params: Mapping[str, object]
) -> tuple[Row, ...]:
    """Run a feature query that MUST be bounded by `%(as_of)s`.

    The missing-parameter check is not pedantry: an unbounded read from
    `games` or `player_game_stats` returns the whole history including
    games after the boundary, which produces a feature set that backtests
    beautifully and cannot be reproduced live.
    """
    _reject_forbidden_identifiers(sql)
    if _AS_OF_PARAM not in sql:
        raise ForbiddenSourceError(
            "<missing as_of filter>",
            "every point-in-time query must reference the %(as_of)s parameter; "
            "an unbounded read is a leak even when the rows look plausible",
        )
    if "as_of" not in params:
        raise ForbiddenSourceError(
            "<missing as_of parameter>",
            "the query references %(as_of)s but no as_of value was supplied",
        )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return tuple(cur.fetchall())


def execute_time_invariant(
    conn: Connection, sql: str, params: Mapping[str, object], *, justification: str
) -> tuple[Row, ...]:
    """Run a feature query for data that has no as-of anchor at all.

    The `justification` argument is required and unused at runtime. That
    is the point: reading unanchored data is allowed, but only by writing
    down why it cannot leak, at the call site, where a reviewer will see
    it. The forbidden-identifier scan still applies, so this is not a
    bypass -- `players.age` is refused here exactly as it is above.
    """
    if not justification.strip():
        raise ForbiddenSourceError(
            "<missing justification>",
            "a query with no as-of bound must record why its data is time-invariant",
        )
    _reject_forbidden_identifiers(sql)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return tuple(cur.fetchall())


# -- team-game grain ---------------------------------------------------

#: Declared here rather than in the step so the SQL and the step's
#: StepProvenance cannot drift: the guard compares this tuple against the
#: columns that actually arrived, so adding a column to the SELECT without
#: adding it here fails on the next run.
#: Fallback for how long after tip-off a result is assumed knowable,
#: used ONLY where games.final_observed_at is NULL -- games already
#: final on first ingest, where nothing witnessed the transition. See
#: db/migrations/0024_game_final_observed_at.sql. A WNBA game runs
#: ~2h15m; four hours is deliberately generous, because being wrong
#: this way drops a few rows near the boundary and being wrong the
#: other way trains on a score that did not exist yet.
DEFAULT_COMPLETION_MARGIN: timedelta = timedelta(hours=4)

TEAM_GAME_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "season_type",
    "start_time",
    "result_known_at",
    "team_id",
    "team_abbrev",
    "team_is_franchise",
    "opponent_team_id",
    "opponent_abbrev",
    "opponent_is_franchise",
    "is_home",
    "points_scored",
    "points_allowed",
    "pace",
    "possessions",
    "offensive_rating",
    "defensive_rating",
    # Style dimensions -- WHAT a team does, as opposed to how well. Rolled
    # into a trailing-window vector by the style steps; see
    # wnba_engine/analysis/style.py for why ratings are excluded from that
    # vector even though they are loaded here.
    "efg",
    "tov_ratio",
    "oreb_pct",
    "ftr",
    "ast_pct",
    "opp_efg",
    "opp_tov_pct",
    "opp_oreb_pct",
    "opp_ftr",
)

_TEAM_GAMES_SQL = """
SELECT
    g.id                         AS game_id,
    g.season                     AS season,
    g.season_type                AS season_type,
    g.start_time                 AS start_time,
    COALESCE(g.final_observed_at, g.start_time + %(completion_margin)s)
                                 AS result_known_at,
    s.team_id                    AS team_id,
    t.abbreviation               AS team_abbrev,
    t.is_franchise               AS team_is_franchise,
    s.opponent_id                AS opponent_team_id,
    o.abbreviation               AS opponent_abbrev,
    o.is_franchise               AS opponent_is_franchise,
    (s.team_id = g.home_team_id) AS is_home,
    CASE WHEN s.team_id = g.home_team_id THEN g.home_score ELSE g.away_score END
                                 AS points_scored,
    CASE WHEN s.team_id = g.home_team_id THEN g.away_score ELSE g.home_score END
                                 AS points_allowed,
    tas.pace                     AS pace,
    tas.possessions              AS possessions,
    tas.offensive_rating         AS offensive_rating,
    tas.defensive_rating         AS defensive_rating,
    tas.effective_field_goal_percentage      AS efg,
    tas.turnover_ratio                       AS tov_ratio,
    tas.offensive_rebound_percentage         AS oreb_pct,
    tas.free_throw_attempt_rate              AS ftr,
    tas.assist_percentage                    AS ast_pct,
    tas.opp_effective_field_goal_percentage  AS opp_efg,
    tas.opp_team_turnover_percentage         AS opp_tov_pct,
    tas.opp_offensive_rebound_percentage     AS opp_oreb_pct,
    tas.opp_free_throw_attempt_rate          AS opp_ftr
FROM games g
CROSS JOIN LATERAL (
    VALUES (g.home_team_id, g.away_team_id), (g.away_team_id, g.home_team_id)
) AS s(team_id, opponent_id)
JOIN teams t ON t.id = s.team_id
JOIN teams o ON o.id = s.opponent_id
LEFT JOIN team_advanced_stats tas
    ON tas.game_id = g.id AND tas.team_id = s.team_id
WHERE COALESCE(g.final_observed_at, g.start_time + %(completion_margin)s)
      <= %(as_of)s
  AND g.status = 'final'
  AND g.season_type = ANY(%(season_types)s::text[])
  AND (%(seasons)s::int[] IS NULL OR g.season = ANY(%(seasons)s::int[]))
ORDER BY g.start_time, g.id, s.team_id
"""


def load_team_games(
    conn: Connection,
    *,
    as_of: datetime,
    season_types: Sequence[str],
    seasons: Sequence[int] | None,
    completion_margin: timedelta = DEFAULT_COMPLETION_MARGIN,
) -> tuple[Row, ...]:
    """One row per (game, team) for games that FINISHED before `as_of`.

    Two rows per game, not one: rest days, back-to-backs, and rolling form
    are all properties of a TEAM's schedule, and a game-grain frame would
    force every such feature to be computed twice with a home/away suffix.

    `status = 'final'` is load-bearing alongside the timestamp filter. A
    game's score is written by ingestion whenever ESPN reports it, and
    `games` carries no "when did we learn this" column -- so the only
    honest way to avoid consuming a score before it existed is to require
    the game to be over, and (see the loading step) to require it to have
    been over comfortably before the boundary.
    """
    return execute_point_in_time(
        conn,
        _TEAM_GAMES_SQL,
        {
            "as_of": as_of,
            "season_types": list(season_types),
            "seasons": list(seasons) if seasons else None,
            "completion_margin": completion_margin,
        },
    )


# -- player-game grain -------------------------------------------------

PLAYER_GAME_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "season_type",
    "start_time",
    "result_known_at",
    "player_id",
    "player_name",
    "team_id",
    "team_abbrev",
    "opponent_team_id",
    "is_home",
    "minutes",
    "points",
    "rebounds",
    "assists",
    "three_pointers_made",
    "starter",
    "did_not_play",
    # -- attempt counts and the remaining counting stats ---------------
    # Needed for the per-36 rates and shot-mix shares that
    # analysis/style.py's PLAYER_DIMENSIONS are built from. They were
    # absent because the original frame only served rolling points /
    # rebounds / assists; a share needs its own denominator in the same
    # row or the ratio has to be taken across rows, which is the "mean of
    # ratios" MODELING_FINDINGS.md measures as biased.
    "field_goals_attempted",
    "three_pointers_attempted",
    "free_throws_attempted",
    "offensive_rebounds",
    "steals",
    "blocks",
    "turnovers",
    # -- balldontlie advanced stats, LEFT JOINed -----------------------
    # Rates the box score cannot produce. Null wherever balldontlie has no
    # advanced row for an ESPN box-score row: 28,989 of 31,340 matched as
    # of 2026-08-02, so expect ~7.5% null and treat it the way `pace` is
    # treated at team grain.
    "usage_pct",
    "true_shooting_pct",
    "assist_pct",
    "rebound_pct",
    "pie",
)

_PLAYER_GAMES_SQL = """
SELECT
    g.id                            AS game_id,
    g.season                        AS season,
    g.season_type                   AS season_type,
    g.start_time                    AS start_time,
    COALESCE(g.final_observed_at, g.start_time + %(completion_margin)s)
                                    AS result_known_at,
    pgs.player_id                   AS player_id,
    p.full_name                     AS player_name,
    pgs.team_id                     AS team_id,
    t.abbreviation                  AS team_abbrev,
    CASE WHEN pgs.team_id = g.home_team_id THEN g.away_team_id ELSE g.home_team_id END
                                    AS opponent_team_id,
    (pgs.team_id = g.home_team_id)  AS is_home,
    pgs.minutes                     AS minutes,
    pgs.points                      AS points,
    pgs.rebounds                    AS rebounds,
    pgs.assists                     AS assists,
    pgs.three_pointers_made         AS three_pointers_made,
    pgs.starter                     AS starter,
    pgs.did_not_play                AS did_not_play,
    pgs.field_goals_attempted       AS field_goals_attempted,
    pgs.three_pointers_attempted    AS three_pointers_attempted,
    pgs.free_throws_attempted       AS free_throws_attempted,
    pgs.offensive_rebounds          AS offensive_rebounds,
    pgs.steals                      AS steals,
    pgs.blocks                      AS blocks,
    pgs.turnovers                   AS turnovers,
    pas.usage_percentage                AS usage_pct,
    pas.true_shooting_percentage        AS true_shooting_pct,
    pas.assist_percentage               AS assist_pct,
    pas.rebound_percentage              AS rebound_pct,
    pas.pie                             AS pie
FROM player_game_stats pgs
JOIN games g   ON g.id = pgs.game_id
JOIN players p ON p.id = pgs.player_id
JOIN teams t   ON t.id = pgs.team_id
-- The advanced source is pinned explicitly even though balldontlie is
-- currently the only one. player_advanced_stats is UNIQUE(game_id,
-- player_id, source), so a second provider appearing would silently turn
-- one row per (player, game) into two -- exactly the doubling that
-- player_game_stats.source already caused once and that this loader's
-- own box_score_source filter exists to prevent.
LEFT JOIN player_advanced_stats pas
       ON pas.game_id = pgs.game_id
      AND pas.player_id = pgs.player_id
      AND pas.source = %(advanced_source)s
-- `result_known_at`, NOT `start_time`. This filter read
-- `g.start_time <= %(as_of)s` until 2026-08-02, which admitted a game
-- that TIPPED OFF before the boundary and finished after it -- and then
-- declared result_known_at as an as-of anchor, so the guard rejected the
-- frame it had just built. `uv run wnba-engine build-features --as-of
-- 2026-07-29 --strategy player_form`, the example in the package README,
-- raised LeakageError on a game starting 2026-07-28T23:30Z. The guard
-- was right: the box score of a game still being played is not
-- observable at the boundary. The team-game query above always used the
-- COALESCE form; this one was not updated when
-- db/migrations/0024_game_final_observed_at.sql landed.
WHERE pgs.source = %(box_score_source)s
  AND COALESCE(g.final_observed_at, g.start_time + %(completion_margin)s)
      <= %(as_of)s
  AND g.status = 'final'
  AND g.season_type = ANY(%(season_types)s::text[])
  AND (%(seasons)s::int[] IS NULL OR g.season = ANY(%(seasons)s::int[]))
ORDER BY g.start_time, g.id, pgs.player_id
"""


def load_player_games(
    conn: Connection,
    *,
    as_of: datetime,
    season_types: Sequence[str],
    seasons: Sequence[int] | None,
    box_score_source: str,
    advanced_source: str,
    completion_margin: timedelta = DEFAULT_COMPLETION_MARGIN,
) -> tuple[Row, ...]:
    """One row per (game, player) from ONE box-score source, with that
    player's advanced rates for the same game LEFT JOINed on.

    `box_score_source` has no default on purpose. player_game_stats holds
    two independent sources for the same games -- 31,096 ESPN rows and
    29,237 balldontlie rows as of 2026-07-29 -- and DATA_INVENTORY.md is
    explicit that the second exists for cross-source validation, not
    extra coverage. Omitting the filter silently doubles most players'
    game counts and halves every per-game average, which looks like a
    modelling problem rather than a query bug. `advanced_source` has no
    default for the same reason, one table over.

    THE TWO SIDES OF THIS JOIN COME FROM DIFFERENT PROVIDERS. The box
    score is ESPN by default and player_advanced_stats is balldontlie
    only, joined on our canonical (game_id, player_id) rather than on
    either provider's ids -- which is exactly what the provider_entity_map
    crosswalk exists to make possible, and why AGENTS.md's warning that
    "balldontlie issues different player ids for the same person across
    its own endpoints" does not bite here. Verified against this database
    on 2026-08-02: 28,989 of 31,340 ESPN rows find an advanced row, i.e.
    92.5%, ranging 87.8% (2026) to 94.0% (2024). The missing 7.5% get
    nulls, which is the honest answer and the same shape `pace` already
    has at team grain.

    NOT SELECTED, deliberately: `player_advanced_stats.minutes`. It is
    TEXT in "MM:SS" form ("37:46") while `player_game_stats.minutes` is
    an INTEGER, and FEATURE_ROADMAP.md ss5 flags the mismatch as the
    hazard for this row. Reading both would put two differently-typed
    minutes columns in one frame and make "which minutes did that rate
    divide by" a question rather than a fact. Every rate built on this
    frame uses the integer.
    """
    return execute_point_in_time(
        conn,
        _PLAYER_GAMES_SQL,
        {
            "as_of": as_of,
            "season_types": list(season_types),
            "seasons": list(seasons) if seasons else None,
            "box_score_source": box_score_source,
            "advanced_source": advanced_source,
            "completion_margin": completion_margin,
        },
    )


# -- standings snapshots ----------------------------------------------

STANDINGS_SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "standings_wins",
    "standings_losses",
    "standings_win_pct",
    "standings_games_behind",
    "standings_playoff_seed",
    "standings_captured_at",
)

_STANDINGS_SNAPSHOT_SQL = """
SELECT
    h.team_id             AS team_id,
    h.season              AS season,
    h.wins                AS standings_wins,
    h.losses              AS standings_losses,
    h.win_percentage      AS standings_win_pct,
    h.games_behind        AS standings_games_behind,
    h.playoff_seed        AS standings_playoff_seed,
    h.captured_at         AS standings_captured_at
FROM team_standings_history h
WHERE h.captured_at <= %(as_of)s
  AND (%(seasons)s::int[] IS NULL OR h.season = ANY(%(seasons)s::int[]))
ORDER BY h.team_id, h.season, h.captured_at
"""


def load_standings_snapshots(
    conn: Connection, *, as_of: datetime, seasons: Sequence[int] | None
) -> tuple[Row, ...]:
    """EVERY standings snapshot at or before `as_of`, oldest first.

    Deliberately not `DISTINCT ON (team_id, season) ... ORDER BY
    captured_at DESC`. That query -- "the latest standings we knew by the
    boundary" -- is the obvious one and it leaks: joined onto a full-season
    training frame it gives a game played in May the record as it stood in
    July. The caller (AsOfJoinStep) needs the whole series so it can pick
    the snapshot that preceded each individual game.

    The table is small enough for that to be free: 138 rows across five
    seasons as of 2026-07-29.

    This is the append-only companion table, NOT `team_standings` -- see
    `_FORBIDDEN_IDENTIFIERS`. Expect NOTHING for historical boundaries:
    the earliest captured_at in this database is 2026-07-09, because
    history only started being recorded when migration 0015 landed. That
    emptiness is the honest answer to "what were the standings, as far as
    we knew, in 2023" -- we did not know. Backfilling it from today's
    team_standings would be inventing data.
    """
    return execute_point_in_time(
        conn,
        _STANDINGS_SNAPSHOT_SQL,
        {"as_of": as_of, "seasons": list(seasons) if seasons else None},
    )


# -- player bio (time-invariant) --------------------------------------

PLAYER_BIO_COLUMNS: tuple[str, ...] = (
    "player_height",
    "player_weight",
    "player_college",
)

_PLAYER_BIO_SQL = """
SELECT
    p.id      AS player_id,
    p.height  AS player_height,
    p.weight  AS player_weight,
    p.college AS player_college
FROM players p
"""

_PLAYER_BIO_JUSTIFICATION = (
    "height/weight/college are described by DATA_INVENTORY.md as 'effectively "
    "permanent', unlike age/jersey_number which are 'refreshed on every "
    "re-ingestion'. players carries no captured_at, so there is no anchor to "
    "filter on; the mutable siblings are refused by the identifier scan, so the "
    "only fields reachable here are ones whose value on game day equals their "
    "value today."
)


def load_player_bios(conn: Connection) -> tuple[Row, ...]:
    """Permanent biographical fields, keyed by player_id.

    Deliberately no as_of parameter -- see the justification above and
    `execute_time_invariant`'s docstring for why that is a declaration
    rather than an oversight.
    """
    return execute_time_invariant(
        conn, _PLAYER_BIO_SQL, {}, justification=_PLAYER_BIO_JUSTIFICATION
    )
