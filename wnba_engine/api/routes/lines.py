"""Sportsbook lines: closing numbers, movement, and results against them.

Read-only, like everything else here. There is no order placement anywhere in
this codebase and none should be added (ROADMAP.md non-goals).

A note that belongs on every response these serve: the sportsbook feed stopped
on 2026-08-10 when its upstream API key lapsed. Historical lines are complete
back to 2022; live ones resume when that key is restored.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from psycopg import Connection

from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import betting_repo

router = APIRouter(tags=["lines"])

# Closing lines never change once a game is final.
SETTLED_MAX_AGE = 3600
LIVE_MAX_AGE = 120

PROP_TYPES = ("points", "rebounds", "assists", "threes", "points_rebounds_assists")


def _season(season: int | None) -> int:
    return season or datetime.now(UTC).year


@router.get("/lines/closing")
def closing_lines(
    response: Response,
    game_ids: str = Query(..., description="Comma-separated game ids."),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Consensus closing spread, total and moneyline for a set of games.

    Consensus is built per book first -- each vendor's last quote before tip --
    and only then averaged, so a book that repriced forty times does not
    outvote one that posted twice.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_MAX_AGE}"
    ids = [int(value) for value in game_ids.split(",") if value.strip().isdigit()][:500]
    return {"lines": betting_repo.fetch_closing_lines(conn, ids)}


@router.get("/games/{game_id}/lines")
def line_movement(
    game_id: int,
    response: Response,
    limit: int = Query(500, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Every quote recorded for one game, per book, oldest first."""
    response.headers["Cache-Control"] = f"public, max-age={LIVE_MAX_AGE}"
    movement = betting_repo.fetch_line_movement(conn, game_id, limit=limit)
    return {"game_id": game_id, "movement": movement, "count": len(movement)}


@router.get("/teams/{team_id}/betting")
def team_betting_record(
    team_id: int,
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """A team's record against the closing spread and total.

    Pushes are excluded from both sides of every rate: a 3-point favourite
    winning by exactly 3 neither covered nor failed to.
    """
    response.headers["Cache-Control"] = f"public, max-age={SETTLED_MAX_AGE}"
    resolved = _season(season)
    return {
        "season": resolved,
        "record": betting_repo.fetch_team_betting_record(conn, team_id, season=resolved),
    }


@router.get("/players/{player_id}/props")
def player_props(
    player_id: int,
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    prop_type: str | None = Query(None, description="Restrict the log to one prop market."),
    limit: int = Query(25, ge=1, le=200),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Closing prop lines against what the player actually did.

    The summary covers every market with a graded line; the log details one.
    """
    response.headers["Cache-Control"] = f"public, max-age={SETTLED_MAX_AGE}"
    summary = betting_repo.fetch_player_prop_summary(conn, player_id, season=season)
    chosen = prop_type if prop_type in PROP_TYPES else (
        summary[0]["prop_type"] if summary else None
    )
    log = (
        betting_repo.fetch_player_prop_log(conn, player_id, prop_type=str(chosen), limit=limit)
        if chosen
        else []
    )
    return {"player_id": player_id, "summary": summary, "prop_type": chosen, "log": log}


@router.get("/lines/market-props")
def market_props(
    response: Response,
    player_id: int | None = Query(None),
    game_id: int | None = Query(None),
    limit: int = Query(300, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Live player props from Kalshi and Polymarket.

    These are the props that still arrive. The sportsbook prop feed is paid and
    its key lapsed on 2026-08-03; the prediction markets are free, unmetered and
    captured every thirty minutes, and were sitting unused while the site
    reported that no props existed.

    Both venues are normalised to one shape -- a line and the probability of
    going over it. Kalshi quotes thresholds ("15+ points"), which is 15 or more,
    so the comparable line is 14.5.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_MAX_AGE}"
    props = betting_repo.fetch_market_props(
        conn, player_id=player_id, game_id=game_id, limit=limit
    )
    return {"props": props, "count": len(props)}


@router.get("/lines/props")
def prop_market(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """League-wide over/under rates by prop market.

    The headline is that overs lose across every market. That is a real and
    well-documented bias, and it is NOT a strategy: MODELING_FINDINGS.md records
    that blanket under-betting returns -2.05% to -10.68% once graded at prices
    that could actually be taken. The vig is larger than the edge.
    """
    response.headers["Cache-Control"] = f"public, max-age={SETTLED_MAX_AGE}"
    return {
        "season": season,
        "markets": betting_repo.fetch_prop_market_summary(conn, season=season),
    }
