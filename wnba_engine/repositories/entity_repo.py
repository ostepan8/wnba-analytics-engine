"""Canonical teams/players/games + the provider_entity_map crosswalk.

resolve_or_create_* functions implement the crosswalk contract: look up
(provider, entity_type, external_id); on a miss, create the canonical row
and the mapping in one transaction-scoped step and return the internal id.
"""

from __future__ import annotations

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
            "start_time = %s, updated_at = now() WHERE id = %s",
            (game.status.value, game.home_score, game.away_score, game.start_time, existing),
        )
        return existing
    row = conn.execute(
        "INSERT INTO games (season, start_time, home_team_id, away_team_id, status, "
        "home_score, away_score) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            game.season,
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
