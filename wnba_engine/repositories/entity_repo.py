"""Canonical teams/players/games + the provider_entity_map crosswalk.

resolve_or_create_* functions implement the crosswalk contract: look up
(provider, entity_type, external_id); on a miss, create the canonical row
and the mapping in one transaction-scoped step and return the internal id.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta

from psycopg import Connection

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
    """
    existing = lookup_internal_id(conn, provider, ENTITY_GAME, game.external_id)
    if existing is not None:
        conn.execute(
            "UPDATE games SET status = %s, home_score = %s, away_score = %s, "
            "start_time = %s, season_type = %s, updated_at = now() WHERE id = %s",
            (
                game.status.value,
                game.home_score,
                game.away_score,
                game.start_time,
                game.season_type.value,
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


def find_player_by_name(conn: Connection, full_name: str) -> int | None:
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
    """
    row = conn.execute("SELECT id FROM players WHERE full_name ILIKE %s", (full_name,)).fetchone()
    if row is not None:
        return int(row[0])

    folded_target = _fold_diacritics(full_name).lower()
    for player_id, candidate in conn.execute("SELECT id, full_name FROM players").fetchall():
        if _fold_diacritics(candidate).lower() == folded_target:
            return int(player_id)
    return None


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


def resolve_or_create_player_by_name(
    conn: Connection,
    provider: str,
    external_id: str,
    full_name: str,
    position: str | None,
) -> int:
    """Crosswalk contract for a provider whose player rarely has a
    reliable external id shared with ESPN (e.g. balldontlie's numeric ids
    are a different id space entirely). Falls back to matching an existing
    canonical player by name before ever creating a new one, so a second
    provider's data joins onto the SAME player ESPN's box scores already
    populated instead of forking a duplicate, historyless identity.
    """
    existing = lookup_internal_id(conn, provider, ENTITY_PLAYER, external_id)
    if existing is not None:
        return existing

    by_name = find_player_by_name(conn, full_name)
    if by_name is not None:
        _insert_mapping(conn, provider, ENTITY_PLAYER, external_id, by_name)
        return by_name

    row = conn.execute(
        "INSERT INTO players (full_name, position) VALUES (%s, %s) RETURNING id",
        (full_name, position),
    ).fetchone()
    assert row is not None
    player_id = int(row[0])
    _insert_mapping(conn, provider, ENTITY_PLAYER, external_id, player_id)
    return player_id
