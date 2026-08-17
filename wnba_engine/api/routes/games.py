"""Games, and the price history attached to one.

Cache-Control is set per endpoint rather than globally because the underlying
data moves at very different speeds: a finished game from 2024 is immutable,
while a game in progress changes every two minutes. Cloudflare honours these in
front of the tunnel, which is what keeps a public endpoint from turning every
page load into a query against a machine at home.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import Connection

from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo

router = APIRouter(prefix="/games", tags=["games"])

FINISHED_GAME_MAX_AGE = 3600
LIVE_DATA_MAX_AGE = 60


@router.get("")
def list_games(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100, description="Season year, e.g. 2026."),
    since: date | None = Query(None, description="Only games starting on or after this date."),
    limit: int = Query(50, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Most recent games first, with team names and final scores."""
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    games = analytics_repo.fetch_recent_games(conn, season=season, since=since, limit=limit)
    return {"games": games, "count": len(games)}


@router.get("/{game_id}")
def get_game(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    game = analytics_repo.fetch_game(conn, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"no game with id {game_id}")
    # A final game will never change again; anything else might.
    is_final = game.get("status") == "final"
    max_age = FINISHED_GAME_MAX_AGE if is_final else LIVE_DATA_MAX_AGE
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return game


@router.get("/{game_id}/odds")
def game_odds(
    game_id: int,
    response: Response,
    limit: int = Query(500, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Sportsbook line movement for one game, oldest first, ready to chart."""
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    history = analytics_repo.fetch_game_odds_history(conn, game_id, limit=limit)
    return {"game_id": game_id, "odds": history, "count": len(history)}


@router.get("/{game_id}/flow")
def game_flow(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Score margin through the game, one point per scoring play.

    Only scoring plays: the other ~85% of play-by-play rows leave the margin
    unchanged and would quadruple the payload to draw the same staircase.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    plays = analytics_repo.fetch_game_flow(conn, game_id)
    return {"game_id": game_id, "plays": plays, "count": len(plays)}


@router.get("/{game_id}/markets")
def game_markets(
    game_id: int,
    response: Response,
    limit: int = Query(500, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Prediction-market implied probabilities for one game, both venues."""
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    prices = analytics_repo.fetch_game_market_prices(conn, game_id, limit=limit)
    return {"game_id": game_id, "prices": prices, "count": len(prices)}
