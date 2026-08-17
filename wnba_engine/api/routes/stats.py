"""Player statistics."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from psycopg import Connection

from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo

router = APIRouter(tags=["stats"])

LEADERS_MAX_AGE = 900

# Below this, a hot three-game stretch outranks a full season and the board
# stops describing anything. Applied by default and adjustable per request.
DEFAULT_MIN_GAMES = 5


@router.get("/leaders")
def leaders(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100, description="Defaults to the current year."),
    min_games: int = Query(DEFAULT_MIN_GAMES, ge=1, le=100),
    limit: int = Query(25, ge=1, le=200),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Season per-game averages, ranked by points.

    Averages cover games actually played -- did-not-play rows carry NULL minutes
    and would otherwise drag every average toward zero.
    """
    response.headers["Cache-Control"] = f"public, max-age={LEADERS_MAX_AGE}"
    resolved_season = season or datetime.now(UTC).year
    rows = analytics_repo.fetch_leaders(
        conn, season=resolved_season, min_games=min_games, limit=limit
    )
    return {"season": resolved_season, "min_games": min_games, "leaders": rows}
