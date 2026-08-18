"""Shot charts, shooting splits, and usage-vs-efficiency.

The binning happens in SQL rather than here. A season is ~30,000 shots and a
chart can resolve a few hundred positions, so sending them raw would be a
multi-megabyte payload thrown away by the renderer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from psycopg import Connection

from wnba_engine.analysis.playoff_race import PLAYOFF_SPOTS, rank_teams
from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo

router = APIRouter(tags=["shooting"])

# Completed seasons never change; the current one gains shots nightly.
SEASON_MAX_AGE = 3600

# Grid cell size in the NBA coordinate system's tenths of a foot. 20 = 2 feet,
# which is fine enough to separate a corner three from an above-the-break one
# and coarse enough that most cells carry a readable sample.
DEFAULT_BIN_SIZE = 20


def _season(season: int | None) -> int:
    return season or datetime.now(UTC).year


@router.get("/standings")
def standings(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Standings with a real playoff seed, clinch status and magic number.

    The seed is computed league-wide (see wnba_engine/analysis/playoff_race.py),
    NOT taken from the provider -- its `playoff_seed` is a conference ranking and
    is passed through separately as `conference_seed`.
    """
    response.headers["Cache-Control"] = f"public, max-age={SEASON_MAX_AGE}"
    resolved = _season(season)
    rows = analytics_repo.fetch_standings(conn, season=resolved)
    ranked = rank_teams(rows)
    return {
        "season": resolved,
        "playoff_spots": PLAYOFF_SPOTS,
        "standings": ranked,
        # Whether the race is live at all. The off-season and a decided season
        # look identical from the rows alone, and a "clinched" badge on every
        # team reads as a bug rather than as a finished season.
        "race_open": any(
            not row["clinched"] and not row["eliminated"] for row in ranked
        ),
    }


@router.get("/shots")
def shot_chart(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    player_id: int | None = Query(None, description="Restrict to one player."),
    team_id: int | None = Query(None, description="Restrict to one team."),
    bin_size: int = Query(DEFAULT_BIN_SIZE, ge=5, le=50),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Shot attempts and makes, binned onto a half-court grid.

    Coordinates are the standard NBA system in tenths of a foot: `x` runs
    [-250, 250] across the floor and `y` from the hoop at 0 toward half court,
    so a client can draw the court without a second lookup.
    """
    response.headers["Cache-Control"] = f"public, max-age={SEASON_MAX_AGE}"
    resolved = _season(season)
    cells = analytics_repo.fetch_shot_chart(
        conn, season=resolved, player_id=player_id, team_id=team_id, bin_size=bin_size
    )
    zones = analytics_repo.fetch_shot_zones(
        conn, season=resolved, player_id=player_id, team_id=team_id
    )
    attempts = sum(int(cell["attempts"]) for cell in cells)
    points = sum(int(cell["points"]) for cell in cells)
    return {
        "season": resolved,
        "bin_size": bin_size,
        "cells": cells,
        "zones": zones,
        "attempts": attempts,
        # The midpoint a diverging colour scale should be centred on. Returned
        # rather than hardcoded in the client so "average" always means this
        # season's actual average, not a number that silently ages.
        "points_per_attempt": round(points / attempts, 4) if attempts else None,
    }


@router.get("/teams/{team_id}/shots/recent")
def team_recent_shot_chart(
    team_id: int,
    response: Response,
    last_n_games: int = Query(
        5, ge=1, le=20, description="How many of the team's most recent final games to include."
    ),
    bin_size: int = Query(DEFAULT_BIN_SIZE, ge=5, le=50),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """A team's shot chart windowed by recent games rather than by season.

    Built for previewing a game that hasn't been played yet: the season chart
    is empty until the season has shots in it, and a single upcoming game has
    none at all by definition. This looks backward instead -- recent form, not
    a preview of a specific matchup.
    """
    # Short-lived: unlike a season total, "recent" changes with every final
    # whistle rather than every 15 minutes.
    response.headers["Cache-Control"] = "public, max-age=300"
    game_ids = analytics_repo.fetch_team_recent_game_ids(
        conn, team_id=team_id, last_n_games=last_n_games
    )
    cells = analytics_repo.fetch_team_recent_shot_chart(
        conn, team_id=team_id, last_n_games=last_n_games, bin_size=bin_size
    )
    zones = analytics_repo.fetch_team_recent_shot_zones(
        conn, team_id=team_id, last_n_games=last_n_games
    )
    attempts = sum(int(cell["attempts"]) for cell in cells)
    points = sum(int(cell["points"]) for cell in cells)
    return {
        "team_id": team_id,
        "games_requested": last_n_games,
        # Early in a season "last 10" may only find 4 -- said plainly rather
        # than silently showing a thinner window as if it were the full one.
        "games_found": len(game_ids),
        "bin_size": bin_size,
        "cells": cells,
        "zones": zones,
        "attempts": attempts,
        "points_per_attempt": round(points / attempts, 4) if attempts else None,
    }


@router.get("/efficiency")
def efficiency(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    min_games: int = Query(10, ge=1, le=100),
    limit: int = Query(200, ge=1, le=500),
    player_id: int | None = Query(None, description="Restrict to one player's row."),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Usage rate against true shooting — volume separated from value."""
    response.headers["Cache-Control"] = f"public, max-age={SEASON_MAX_AGE}"
    resolved = _season(season)
    players = analytics_repo.fetch_efficiency(
        conn, season=resolved, min_games=min_games, limit=limit, player_id=player_id
    )
    return {"season": resolved, "min_games": min_games, "players": players}
