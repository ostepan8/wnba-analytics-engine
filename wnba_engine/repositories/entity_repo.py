"""Canonical teams/players/games + the provider_entity_map crosswalk.

resolve_or_create_* functions implement the crosswalk contract: look up
(provider, entity_type, external_id); on a miss, create the canonical row
and the mapping in one transaction-scoped step and return the internal id.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from datetime import datetime, timedelta

from psycopg import Connection

from wnba_engine import player_aliases
from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.models.games import ScoreboardGame, TeamRef

ENTITY_TEAM = "team"
ENTITY_PLAYER = "player"
ENTITY_GAME = "game"

_SELECT_MAPPING = """
SELECT internal_id FROM provider_entity_map
WHERE provider = %s AND entity_type = %s AND external_id = %s
"""

_INSERT_MAPPING = """
INSERT INTO provider_entity_map (provider, entity_type, external_id, internal_id)
VALUES (%s, %s, %s, %s)
ON CONFLICT (provider, entity_type, external_id) DO NOTHING
"""


def lookup_internal_id(
    conn: Connection, provider: str, entity_type: str, external_id: str
) -> int | None:
    row = conn.execute(_SELECT_MAPPING, (provider, entity_type, external_id)).fetchone()
    return row[0] if row else None


def _insert_mapping(
    conn: Connection, provider: str, entity_type: str, external_id: str, internal_id: int
) -> None:
    conn.execute(_INSERT_MAPPING, (provider, entity_type, external_id, internal_id))


def record_crosswalk_mapping(
    conn: Connection, provider: str, entity_type: str, external_id: str, internal_id: int
) -> None:
    """Public entry point for persisting a crosswalk mapping resolved by
    some OTHER method than a resolve_or_create_* call -- e.g. a game
    matched by team+date (find_game_id_by_teams) rather than by a shared
    provider id. Idempotent: safe to call again for an already-known pair.
    """
    _insert_mapping(conn, provider, entity_type, external_id, internal_id)


def resolve_or_create_team(conn: Connection, provider: str, team: TeamRef) -> int:
    existing = lookup_internal_id(conn, provider, ENTITY_TEAM, team.external_id)
    if existing is not None:
        conn.execute(
            "UPDATE teams SET name = %s, abbreviation = %s, updated_at = now() "
            "WHERE id = %s AND (name <> %s OR abbreviation <> %s)",
            (team.name, team.abbreviation, existing, team.name, team.abbreviation),
        )
        return existing
    row = conn.execute(
        "INSERT INTO teams (name, abbreviation) VALUES (%s, %s) RETURNING id",
        (team.name, team.abbreviation),
    ).fetchone()
    assert row is not None  # RETURNING always yields a row
    team_id = int(row[0])
    _insert_mapping(conn, provider, ENTITY_TEAM, team.external_id, team_id)
    return team_id


def resolve_or_create_player(conn: Connection, provider: str, player: PlayerRef) -> int:
    existing = lookup_internal_id(conn, provider, ENTITY_PLAYER, player.external_id)
    if existing is not None:
        conn.execute(
            "UPDATE players SET full_name = %s, position = %s, updated_at = now() "
            "WHERE id = %s AND (full_name <> %s OR position IS DISTINCT FROM %s)",
            (player.full_name, player.position, existing, player.full_name, player.position),
        )
        return existing
    row = conn.execute(
        "INSERT INTO players (full_name, position) VALUES (%s, %s) RETURNING id",
        (player.full_name, player.position),
    ).fetchone()
    assert row is not None
    player_id = int(row[0])
    _insert_mapping(conn, provider, ENTITY_PLAYER, player.external_id, player_id)
    return player_id


def upsert_game(
    conn: Connection,
    provider: str,
    game: ScoreboardGame,
    *,
    home_team_id: int,
    away_team_id: int,
) -> int:
    """Create or refresh the canonical game row for a provider's game.

    Scores/status are updated in place on re-ingestion (a scheduled game
    becoming final). ESPN is currently the sole score source in this repo;
    when Phase 0 odds/outcomes data is folded in it takes precedence for
    final scores (see 0001 migration comment).

    `final_observed_at` is stamped only on a WITNESSED transition -- a game
    we already held as non-final that is now final. It is deliberately not
    set when inserting a game that is already final, because a backfill
    would then claim every historical result only became knowable on the
    day it was backfilled. `COALESCE` makes the first observation
    permanent: a later re-sync of an already-final game must not move it
    forward. See db/migrations/0024_game_final_observed_at.sql.
    """
    existing = lookup_internal_id(conn, provider, ENTITY_GAME, game.external_id)
    if existing is not None:
        conn.execute(
            "UPDATE games SET status = %s, home_score = %s, away_score = %s, "
            "start_time = %s, season_type = %s, "
            "final_observed_at = CASE "
            "    WHEN %s = 'final' AND games.status <> 'final' "
            "    THEN COALESCE(games.final_observed_at, now()) "
            "    ELSE games.final_observed_at END, "
            "updated_at = now() WHERE id = %s",
            (
                game.status.value,
                game.home_score,
                game.away_score,
                game.start_time,
                game.season_type.value,
                game.status.value,
                existing,
            ),
        )
        return existing
    row = conn.execute(
        "INSERT INTO games (season, season_type, start_time, home_team_id, away_team_id, "
        "status, home_score, away_score) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            game.season,
            game.season_type.value,
            game.start_time,
            home_team_id,
            away_team_id,
            game.status.value,
            game.home_score,
            game.away_score,
        ),
    ).fetchone()
    assert row is not None
    game_id = int(row[0])
    _insert_mapping(conn, provider, ENTITY_GAME, game.external_id, game_id)
    return game_id


def update_game_venue_info(
    conn: Connection, game_id: int, *, venue_name: str | None, attendance: int | None
) -> None:
    """Persist venue_name/attendance parsed from a game's box score summary
    (see espn/parser.py::parse_summary -> GameBoxScore.venue_name/
    attendance). Separate from upsert_game because this data only exists
    once a summary has been fetched and parsed -- upsert_game runs first,
    off the scoreboard payload alone, before it's known whether a summary
    will even be fetched (only final games get one).

    Same update-on-change idiom as resolve_or_create_team/upsert_game:
    IS DISTINCT FROM (not <>, since both columns are nullable and a plain
    <> never matches a NULL against anything) skips the write entirely
    when nothing changed, and never blind-overwrites a previously-known
    value with NULL from a re-ingest whose payload happened to lack
    gameInfo (fail-open parsing already turns "missing" into NULL at parse
    time, so silently keeping the last-known-good value here is the right
    default until/unless a source explicitly reports a change).
    """
    if venue_name is None and attendance is None:
        return
    conn.execute(
        "UPDATE games SET "
        "venue_name = COALESCE(%s, venue_name), "
        "attendance = COALESCE(%s, attendance), "
        "updated_at = now() "
        "WHERE id = %s AND (venue_name IS DISTINCT FROM COALESCE(%s, venue_name) "
        "OR attendance IS DISTINCT FROM COALESCE(%s, attendance))",
        (venue_name, attendance, game_id, venue_name, attendance),
    )


_FIND_GAME_BY_TEAMS_SQL = """
SELECT g.id
FROM games g
JOIN teams th ON th.id = g.home_team_id
JOIN teams ta ON ta.id = g.away_team_id
WHERE (
    (th.name ILIKE %s AND ta.name ILIKE %s)
    OR (th.name ILIKE %s AND ta.name ILIKE %s)
)
AND g.start_time BETWEEN %s AND %s
ORDER BY ABS(EXTRACT(EPOCH FROM (g.start_time - %s)))
LIMIT 1
"""


def find_game_id_by_teams(
    conn: Connection,
    team_a_name: str,
    team_b_name: str,
    near: datetime,
    *,
    window: timedelta,
) -> int | None:
    """Best-effort match: two teams (matched as a case-insensitive substring
    against the canonical team name, e.g. 'Phoenix' matches 'Phoenix
    Mercury') playing each other within `window` of `near`, in either
    home/away order. Used to link data that names teams and a rough date,
    not a canonical game id, to a canonical game (prediction-market
    snapshots, balldontlie's own game ids).

    A substring match, not just a prefix: balldontlie's two newest (2026)
    expansion franchises have an empty city field on their end, so their
    full_name comes back as just "Tempo" or "Fire" instead of "Toronto
    Tempo" / "Portland Fire" -- a prefix match against our canonical name
    misses that entirely, since "Toronto Tempo" doesn't start with "Tempo".
    """
    pattern_a, pattern_b = f"%{team_a_name}%", f"%{team_b_name}%"
    row = conn.execute(
        _FIND_GAME_BY_TEAMS_SQL,
        (
            pattern_a,
            pattern_b,
            pattern_b,
            pattern_a,
            near - window,
            near + window,
            near,
        ),
    ).fetchone()
    return int(row[0]) if row else None


def find_team_by_abbreviation(conn: Connection, abbreviation: str) -> int | None:
    """Read-only lookup by the canonical teams.abbreviation column.

    Used where a source identifies teams by abbreviation only (no id, no
    full name) -- e.g. archived Wayback injury-report pages, which encode
    only a team logo URL. Never creates a team: an abbreviation alone is
    too thin to safely originate a new canonical row, so an unresolved
    abbreviation is the caller's problem to log and skip.
    """
    row = conn.execute("SELECT id FROM teams WHERE abbreviation = %s", (abbreviation,)).fetchone()
    return int(row[0]) if row else None


def find_team_by_name(conn: Connection, name: str) -> int | None:
    """Read-only lookup by the canonical teams.name column (case-insensitive
    exact match). Fallback for when a source's logo-derived abbreviation
    couldn't be extracted at all (see wayback_injuries_parser) but the full
    display name is present -- e.g. "Atlanta Dream". Never creates a team,
    same reasoning as find_team_by_abbreviation.
    """
    row = conn.execute("SELECT id FROM teams WHERE name ILIKE %s", (name,)).fetchone()
    return int(row[0]) if row else None


def _fold_diacritics(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def find_team_by_name_fragment(conn: Connection, fragment: str) -> int | None:
    """Read-only substring lookup by the canonical teams.name column
    (case-insensitive). Used when a source names a team by a short/partial
    city name rather than the full team name -- e.g. Kalshi's team-level
    derivative-market titles say "Atlanta" not "Atlanta Dream" (see
    kalshi/team_market_matching.py). Separate from find_team_by_name
    (exact match) rather than loosening that function's contract, since
    its existing caller (wayback_injuries_parser) relies on exact
    matching against full display names. Never creates a team, same
    reasoning as find_team_by_abbreviation.
    """
    row = conn.execute("SELECT id FROM teams WHERE name ILIKE %s", (f"%{fragment}%",)).fetchone()
    return int(row[0]) if row else None


def find_player_by_name(
    conn: Connection, full_name: str, *, allow_reversed: bool = False
) -> int | None:
    """Read-only lookup by the canonical players.full_name column
    (case-insensitive exact match). Used to resolve a second provider's own
    player id (e.g. balldontlie's, or a Kalshi/Polymarket player-prop
    title) to the SAME canonical player ESPN's box scores already created,
    rather than a name match creating a duplicate identity.

    Falls back to a diacritic-insensitive match if the exact match misses:
    providers don't always agree on accents (Kalshi/Polymarket "Janelle
    Salaün" vs ESPN's "Janelle Salaun"), and Postgres ILIKE is
    accent-sensitive. The fallback is Python-side (small player count, only
    runs on a miss) rather than requiring the Postgres unaccent extension.

    `allow_reversed` adds a further fallback for "Last First" ordering --
    OPT-IN, and deliberately not the default. Verified live: bovada writes
    some the-odds-api player props reversed ("Austin Shakira",
    "Delle Donne Elena") while every other book uses "First Last", and it
    is inconsistent even within a single response, correctly naming some
    players and reversing others. Enabling it for sportsbook prop
    ingestion recovers those rows; enabling it globally would be wrong,
    since find_player_by_name also serves espn_transactions_ingest, which
    extracts names best-effort from free text where a reversed retry would
    manufacture matches out of noise.

    The reversal moves the LAST token to the front rather than swapping a
    pair, so multi-word surnames survive: "Delle Donne Elena" -> "Elena
    Delle Donne". It runs only after both earlier strategies miss, so it
    can never override a name that already resolves.

    Resolution order: exact -> diacritic-folded -> curated alias
    (wnba_engine/player_aliases.py, for name changes and provider
    misspellings) -> reversed order, then reversed-AND-aliased, if opted
    in. Leading/trailing whitespace is stripped up front: providers really
    do emit " Ezi Magbegor" and "Satou Sabally ".
    """
    full_name = full_name.strip()
    row = conn.execute("SELECT id FROM players WHERE full_name ILIKE %s", (full_name,)).fetchone()
    if row is not None:
        return int(row[0])

    candidates = conn.execute("SELECT id, full_name FROM players").fetchall()
    attempts: list[str | None] = [full_name]
    # Curated aliases are exact, individually-verified mappings, so unlike
    # the reversed heuristic below they're safe for every caller.
    attempts.append(player_aliases.canonical_name(full_name))

    if allow_reversed:
        reversed_name = _reverse_name_order(full_name)
        attempts.append(reversed_name)
        if reversed_name is not None:
            # Reversal and aliasing must COMPOSE: bovada wrote "Durr Asia",
            # which reverses to "Asia Durr" -- itself an alias for the
            # canonical "AD Durr". Without this step a name needing BOTH
            # transforms stays silently unresolved.
            attempts.append(player_aliases.canonical_name(reversed_name))

    for attempt in attempts:
        if attempt:
            matched = _match_folded(candidates, attempt)
            if matched is not None:
                return matched
    return None


def _match_folded(candidates: Sequence[tuple[int, str]], target: str) -> int | None:
    """Diacritic-insensitive exact match of `target` against candidate
    full_names -- Postgres ILIKE is accent-sensitive, and this stays
    Python-side (small player count, only runs on a miss) rather than
    requiring the unaccent extension."""
    folded_target = _fold_diacritics(target).lower()
    for player_id, candidate in candidates:
        if _fold_diacritics(candidate).lower() == folded_target:
            return int(player_id)
    return None


def _reverse_name_order(full_name: str) -> str | None:
    """"Austin Shakira" -> "Shakira Austin"; "Delle Donne Elena" -> "Elena
    Delle Donne". None when there's nothing to reverse (a single token).
    """
    parts = full_name.split()
    if len(parts) < 2:
        return None
    return " ".join([parts[-1], *parts[:-1]])


_FIND_RECENT_TEAM_FOR_PLAYER_SQL = """
SELECT pgs.team_id
FROM player_game_stats pgs
JOIN games g ON g.id = pgs.game_id
WHERE pgs.player_id = %s
ORDER BY g.start_time DESC
LIMIT 1
"""


def find_recent_team_id_for_player(conn: Connection, player_id: int) -> int | None:
    """Most recent team a player has a box-score row for, ordered by the
    game's actual start_time (not row insertion order). Used to resolve
    which team a player-prop market's game belongs to when the market
    title names only the player, not a team -- Kalshi player-prop titles
    carry no team name at all (see kalshi/player_prop_matching.py).
    """
    row = conn.execute(_FIND_RECENT_TEAM_FOR_PLAYER_SQL, (player_id,)).fetchone()
    return int(row[0]) if row else None


_FIND_GAME_BY_TEAM_AND_DATE_SQL = """
SELECT id FROM games
WHERE (home_team_id = %s OR away_team_id = %s)
AND start_time BETWEEN %s AND %s
ORDER BY ABS(EXTRACT(EPOCH FROM (start_time - %s)))
LIMIT 1
"""


def find_game_id_by_team_and_date(
    conn: Connection, team_id: int, near: datetime, *, window: timedelta
) -> int | None:
    """Best-effort match: a game the given team plays within `window` of
    `near`. Narrower than find_game_id_by_teams -- used for player-prop
    markets after resolving the player's most recent team via
    find_recent_team_id_for_player, since only one team is known there.
    """
    row = conn.execute(
        _FIND_GAME_BY_TEAM_AND_DATE_SQL,
        (team_id, team_id, near - window, near + window, near),
    ).fetchone()
    return int(row[0]) if row else None


_UPDATE_PLAYER_BIO_SQL = """
UPDATE players SET
    height = %s, weight = %s, jersey_number = %s, college = %s, age = %s,
    updated_at = now()
WHERE id = %s AND (
    height IS DISTINCT FROM %s OR weight IS DISTINCT FROM %s OR
    jersey_number IS DISTINCT FROM %s OR college IS DISTINCT FROM %s OR
    age IS DISTINCT FROM %s
)
"""


def _update_player_bio(
    conn: Connection,
    player_id: int,
    *,
    height: str | None,
    weight: str | None,
    jersey_number: str | None,
    college: str | None,
    age: int | None,
) -> None:
    conn.execute(
        _UPDATE_PLAYER_BIO_SQL,
        (
            height,
            weight,
            jersey_number,
            college,
            age,
            player_id,
            height,
            weight,
            jersey_number,
            college,
            age,
        ),
    )


_LIST_GAMES_IN_RANGE_SQL = """
SELECT id, start_time FROM games
WHERE start_time BETWEEN %s AND %s
ORDER BY start_time
"""


def list_games_in_range(
    conn: Connection, since: datetime, until: datetime
) -> tuple[tuple[int, datetime], ...]:
    """Every canonical game whose start_time falls in [since, until]
    (inclusive both ends). Used by backfill sweeps anchored on OUR games
    table rather than a provider's own schedule -- e.g. the-odds-api
    historical-odds checkpoint backfill, which computes T-7d/T-24h/T-1h/
    closing checkpoints per game from games.start_time (see
    wnba_engine/pipeline/odds_api_ingest.py).
    """
    rows = conn.execute(_LIST_GAMES_IN_RANGE_SQL, (since, until)).fetchall()
    return tuple((int(row[0]), row[1]) for row in rows)


_LIST_EXTERNAL_IDS_SQL = """
SELECT external_id
FROM provider_entity_map
WHERE provider = %s AND entity_type = %s AND internal_id = %s
ORDER BY external_id
"""


def list_external_ids(
    conn: Connection, provider: str, entity_type: str, internal_id: int
) -> tuple[str, ...]:
    """The reverse of lookup_internal_id: every external id one provider
    holds for a canonical row.

    Returns a tuple rather than a single id because the mapping is
    legitimately one-to-many for at least one provider -- the-odds-api
    re-issues an event id partway through a game's quoting life, leaving
    two ids for one game (see DATA_INVENTORY.md's crosswalk quirks). A
    caller that needs "the event id for this game" must be prepared to try
    each, since only one of them is valid at any given historical
    timestamp.
    """
    rows = conn.execute(_LIST_EXTERNAL_IDS_SQL, (provider, entity_type, internal_id)).fetchall()
    return tuple(str(row[0]) for row in rows)


def resolve_or_create_player_by_name(
    conn: Connection,
    provider: str,
    external_id: str,
    full_name: str,
    position: str | None,
    height: str | None,
    weight: str | None,
    jersey_number: str | None,
    college: str | None,
    age: int | None,
) -> int:
    """Crosswalk contract for a provider whose player rarely has a
    reliable external id shared with ESPN (e.g. balldontlie's numeric ids
    are a different id space entirely). Falls back to matching an existing
    canonical player by name before ever creating a new one, so a second
    provider's data joins onto the SAME player ESPN's box scores already
    populated instead of forking a duplicate, historyless identity.

    Bio fields (height/weight/jersey_number/college/age) follow the same
    UPDATE-on-match pattern as resolve_or_create_team/resolve_or_create_player
    above -- applied on BOTH match paths (an existing crosswalk hit, and a
    fresh name match), not just on create. Unlike full_name/position, bio
    data is a snapshot that legitimately drifts over time (a trade changes
    jersey_number, a birthday changes age), so re-ingesting a season should
    keep it current rather than freezing it at first-seen values. This is
    also the mechanism by which an ESPN-only player (ESPN box scores never
    carry bio data at all) gets backfilled with real bio data the first
    time a balldontlie pipeline run resolves onto them by name.
    """
    existing = lookup_internal_id(conn, provider, ENTITY_PLAYER, external_id)
    if existing is not None:
        _update_player_bio(
            conn,
            existing,
            height=height,
            weight=weight,
            jersey_number=jersey_number,
            college=college,
            age=age,
        )
        return existing

    by_name = find_player_by_name(conn, full_name)
    if by_name is not None:
        _insert_mapping(conn, provider, ENTITY_PLAYER, external_id, by_name)
        _update_player_bio(
            conn,
            by_name,
            height=height,
            weight=weight,
            jersey_number=jersey_number,
            college=college,
            age=age,
        )
        return by_name

    row = conn.execute(
        "INSERT INTO players (full_name, position, height, weight, jersey_number, "
        "college, age) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (full_name, position, height, weight, jersey_number, college, age),
    ).fetchone()
    assert row is not None
    player_id = int(row[0])
    _insert_mapping(conn, provider, ENTITY_PLAYER, external_id, player_id)
    return player_id


def list_team_names(conn: Connection) -> list[tuple[int, str]]:
    """Every known team as (id, full name).

    The official injury report identifies a team only by its printed name, and
    the parser needs the real list rather than a regex for "a capitalised
    phrase that might be a team" -- that pattern cannot be told apart from a
    capitalised injury reason, and a wrong match reassigns a player to the
    opposing side.
    """
    rows = conn.execute(
        "SELECT id, name FROM teams WHERE name IS NOT NULL ORDER BY name"
    ).fetchall()
    return [(int(row[0]), str(row[1])) for row in rows]
