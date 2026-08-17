"""Teams and players: the index and detail endpoints the site is built on."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import Connection

from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo

router = APIRouter(tags=["directory"])

# Rosters and profiles change on a transaction, not on a snapshot cadence.
DIRECTORY_MAX_AGE = 900


def _season(season: int | None) -> int:
    return season or datetime.now(UTC).year


@router.get("/teams")
def list_teams(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Franchises only, with this season's record. Excludes the All-Star and
    national sides that share the teams table."""
    response.headers["Cache-Control"] = f"public, max-age={DIRECTORY_MAX_AGE}"
    resolved = _season(season)
    return {"season": resolved, "teams": analytics_repo.fetch_teams(conn, season=resolved)}


@router.get("/teams/{team_id}")
def get_team(
    team_id: int,
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    response.headers["Cache-Control"] = f"public, max-age={DIRECTORY_MAX_AGE}"
    resolved = _season(season)
    team = analytics_repo.fetch_team(conn, team_id, season=resolved)
    if team is None:
        raise HTTPException(status_code=404, detail=f"no team with id {team_id}")
    return {
        "season": resolved,
        "team": team,
        "roster": analytics_repo.fetch_team_roster(conn, team_id, season=resolved),
        "schedule": analytics_repo.fetch_team_schedule(conn, team_id, season=resolved),
    }


@router.get("/players")
def list_players(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    q: str | None = Query(None, min_length=1, max_length=60, description="Name search."),
    limit: int = Query(300, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Players who appeared in the season, ranked by scoring."""
    response.headers["Cache-Control"] = f"public, max-age={DIRECTORY_MAX_AGE}"
    resolved = _season(season)
    players = analytics_repo.fetch_players(conn, season=resolved, query=q, limit=limit)
    return {"season": resolved, "players": players, "count": len(players)}


@router.get("/players/{player_id}")
def get_player(
    player_id: int,
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Profile, per-season averages, and a game log.

    The game log defaults to every season rather than the current one: a player
    who has not appeared this year would otherwise open to an empty page.
    """
    response.headers["Cache-Control"] = f"public, max-age={DIRECTORY_MAX_AGE}"
    player = analytics_repo.fetch_player(conn, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"no player with id {player_id}")
    return {
        "player": player,
        "seasons": analytics_repo.fetch_player_seasons(conn, player_id),
        "game_log": analytics_repo.fetch_player_game_log(conn, player_id, season=season),
    }
