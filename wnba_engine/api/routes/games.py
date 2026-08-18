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

from wnba_engine.analysis import zone_matchups
from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo, game_detail_repo

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


@router.get("/{game_id}/shots")
def game_shots(
    game_id: int,
    response: Response,
    team_id: int | None = Query(None, description="One side only; omit for both."),
    bin_size: int = Query(25, ge=5, le=50),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Shot locations for one game, binned, optionally for a single team.

    A larger default bin than the season chart: one game is a few hundred
    attempts rather than thirty thousand, so finer cells would mostly hold one
    shot each and the chart would read as noise.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    cells = game_detail_repo.fetch_game_shots(
        conn, game_id, team_id=team_id, bin_size=bin_size
    )
    # Individual attempts as well as the grid. One game is too few shots to bin
    # meaningfully -- most cells would hold exactly one -- so the client plots
    # the shots themselves and uses the grid only for the summary numbers.
    shots = game_detail_repo.fetch_game_shot_points(conn, game_id, team_id=team_id)
    attempts = sum(int(cell["attempts"]) for cell in cells)
    points = sum(int(cell["points"]) for cell in cells)
    return {
        "game_id": game_id,
        "team_id": team_id,
        "bin_size": bin_size,
        "cells": cells,
        "shots": shots,
        "attempts": attempts,
        "points_per_attempt": round(points / attempts, 4) if attempts else None,
        "teams": game_detail_repo.fetch_game_teams(conn, game_id),
    }


@router.get("/{game_id}/props")
def game_props(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Player prop lines posted for this game, with what the player did.

    One consensus line per player-market: the prop table holds a row per book,
    so reading it raw counts a six-book game six times.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    props = game_detail_repo.fetch_game_player_props(conn, game_id)
    return {"game_id": game_id, "props": props, "count": len(props)}


@router.get("/{game_id}/box")
def game_box_score(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Per-player box score, one row per player.

    player_game_stats is keyed by SOURCE, so a raw select returns each player
    once per provider; DISTINCT ON collapses to the preferred feed.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"
    rows = analytics_repo.fetch_game_box_score(conn, game_id)
    return {"game_id": game_id, "players": rows, "count": len(rows)}


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


@router.get("/{game_id}/zone-matchups")
def game_zone_matchups(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Rotation players on both sides with a real zone edge against tonight's
    specific opponent -- see wnba_engine/analysis/zone_matchups.py for what
    "real" means here and why it's season-long on both sides, not this
    pairing's own (far too little volume for that).
    """
    game = analytics_repo.fetch_game(conn, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"no game with id {game_id}")
    response.headers["Cache-Control"] = f"public, max-age={LIVE_DATA_MAX_AGE}"

    season = int(game["season"])
    home_id = int(game["home_team_id"])
    away_id = int(game["away_team_id"])

    rosters = {
        home_id: analytics_repo.fetch_team_roster(conn, home_id, season=season),
        away_id: analytics_repo.fetch_team_roster(conn, away_id, season=season),
    }
    rotation_ids = [
        int(player["player_id"])
        for roster in rosters.values()
        for player in roster[: zone_matchups.PLAYERS_PER_TEAM]
    ]
    player_zone_rows = analytics_repo.fetch_players_shot_zones(
        conn, player_ids=rotation_ids, season=season
    )
    player_zones: dict[int, list[dict[str, object]]] = {}
    for row in player_zone_rows:
        player_zones.setdefault(int(row["player_id"]), []).append(row)

    defense_zones = {
        home_id: game_detail_repo.fetch_shot_defence_zones(conn, home_id, season=season),
        away_id: game_detail_repo.fetch_shot_defence_zones(conn, away_id, season=season),
    }
    league_zones = analytics_repo.fetch_shot_zones(
        conn, season=season, player_id=None, team_id=None
    )

    edges = zone_matchups.compute_zone_edges(
        rosters=rosters,
        player_zones=player_zones,
        defense_zones=defense_zones,
        league_zones=league_zones,
        opponent_of={home_id: away_id, away_id: home_id},
    )
    return {
        "game_id": game_id,
        "season": season,
        "edges": [
            {
                "player_id": edge.player_id,
                "full_name": edge.full_name,
                "team_id": edge.team_id,
                "opponent_team_id": edge.opponent_team_id,
                "zone": edge.zone,
                "player_rate": round(edge.player_rate, 4),
                "defense_rate": round(edge.defense_rate, 4),
                "league_rate": round(edge.league_rate, 4),
            }
            for edge in edges[:15]
        ],
    }
