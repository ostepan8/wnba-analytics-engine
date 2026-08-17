"""A whole day of games in one request.

The scoreboard needs the same context for every game on it: each team's record,
form, rest and injury report, plus the props across the day whose live price and
recent frequency disagree most. Fetching that per game would be a dozen round
trips to render one screen, and every one of them would repeat the same player
history query.

Everything is cut at the earliest tip-off on the slate. Games on one day are on
one day: no player has a result from a later game on the same slate, so a single
cut is both correct and one query instead of one per game.

Read-only. There is no order placement anywhere in this codebase (ROADMAP.md
non-goals), and the ranked trends are a sort, not a recommendation -- see
wnba_engine/analysis/slate.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import Connection

from wnba_engine.analysis.prop_trends import (
    attach_trends,
    group_history,
    opponents_in_game,
)
from wnba_engine.analysis.slate import (
    TOP_SLATE_TRENDS,
    gap_balance,
    rank_slate_trends,
)
from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo, betting_repo, form_repo

router = APIRouter(tags=["slate"])

LIVE_MAX_AGE = 120

# A day holds at most six WNBA games; the ceiling is a guard against someone
# asking for a season in one call, not a real constraint on a slate.
MAX_GAMES = 20

# Props per game to price. The venues list a few dozen per game, so this is
# headroom rather than a cut.
PROPS_PER_GAME = 300

# Ruled out or unlikely. "Day-To-Day" and "Questionable" are explicitly NOT
# here: a questionable player is expected to be a game-time decision, and
# counting her as unavailable overstates what her team actually filed.
OUT_STATUSES = ("out", "doubtful")


def _parse_ids(raw: str) -> list[int]:
    """Comma-separated game ids, validated at the boundary."""
    ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            raise HTTPException(
                status_code=422, detail=f"game_ids must be integers, got {chunk!r}"
            )
        ids.append(int(chunk))
    unique = sorted(set(ids))
    if not unique:
        raise HTTPException(status_code=422, detail="game_ids is empty")
    if len(unique) > MAX_GAMES:
        raise HTTPException(
            status_code=422, detail=f"at most {MAX_GAMES} games per request"
        )
    return unique


def _is_out(status: str | None) -> bool:
    return any(word in (status or "").lower() for word in OUT_STATUSES)


def _rest_days(tip: datetime, last_game_at: datetime | None) -> int | None:
    """Days between a team's previous game and this one.

    Rest is a real driver of scoring and is otherwise invisible on a scoreboard.
    """
    if last_game_at is None:
        return None
    return max((tip - last_game_at).days, 0)


@router.get("/slate")
def slate(
    response: Response,
    game_ids: str = Query(..., description="Comma-separated game ids, one day's worth."),
    limit: int = Query(TOP_SLATE_TRENDS, ge=1, le=50),
    conn: Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Context for every game on a slate, plus the day's most divergent props."""
    response.headers["Cache-Control"] = f"public, max-age={LIVE_MAX_AGE}"

    ids = _parse_ids(game_ids)
    games = [game for game in (analytics_repo.fetch_game(conn, gid) for gid in ids) if game]
    if not games:
        raise HTTPException(status_code=404, detail="no games with those ids")

    season = int(games[0]["season"]) if games[0].get("season") else datetime.now(UTC).year
    earliest = min(game["start_time"] for game in games)

    team_ids = sorted(
        {int(game["home_team_id"]) for game in games}
        | {int(game["away_team_id"]) for game in games}
    )
    form = form_repo.fetch_team_form(conn, team_ids, season=season, before=str(earliest))
    injuries = form_repo.fetch_current_injuries(conn, team_ids)

    # A team plays once a day, so its rest is measured against the one game it
    # appears in on this slate.
    tip_by_team = {
        team_id: game["start_time"]
        for game in games
        for team_id in (int(game["home_team_id"]), int(game["away_team_id"]))
    }

    teams: dict[str, Any] = {}
    for team_id in team_ids:
        listed = [row for row in injuries if row.get("team_id") == team_id]
        teams[str(team_id)] = {
            "team_id": team_id,
            "form": dict(form.get(team_id) or {}),
            "rest_days": _rest_days(
                tip_by_team[team_id], (form.get(team_id) or {}).get("last_game_at")
            ),
            "betting": betting_repo.fetch_team_betting_record(conn, team_id, season=season),
            "out": [row for row in listed if _is_out(row.get("status"))],
            "listed": len(listed),
        }

    # One history query for the whole day. Props first, so only players who are
    # actually priced today are fetched.
    props_by_game = {
        int(game["id"]): betting_repo.fetch_market_props(
            conn, game_id=int(game["id"]), limit=PROPS_PER_GAME
        )
        for game in games
    }
    all_props = [prop for props in props_by_game.values() for prop in props]

    enriched: list[dict[str, Any]] = []
    if all_props:
        player_ids = sorted({int(prop["player_id"]) for prop in all_props})
        history = group_history(
            form_repo.fetch_player_stat_history(
                conn, player_ids, before=str(earliest), season=season
            )
        )
        for game in games:
            props = props_by_game[int(game["id"])]
            if not props:
                continue
            enriched.extend(
                attach_trends(
                    props,
                    history=history,
                    opponent_of=opponents_in_game(
                        history,
                        home_team_id=int(game["home_team_id"]),
                        away_team_id=int(game["away_team_id"]),
                    ),
                )
            )

    # Props belonging to players who have been ruled out are not ranked. The
    # venues price a scratched player's over near zero, so without this every
    # top row is a player who is not playing.
    ruled_out = {
        int(row["player_id"])
        for team in teams.values()
        for row in team["out"]
        if row.get("player_id") is not None
    }

    lines = betting_repo.fetch_closing_lines(conn, [int(game["id"]) for game in games])
    totals = [
        float(line["total"])
        for line in lines.values()
        if line.get("total") is not None
    ]

    return {
        "season": season,
        "games": [
            {
                "game_id": int(game["id"]),
                "start_time": game["start_time"],
                "home_team_id": int(game["home_team_id"]),
                "away_team_id": int(game["away_team_id"]),
            }
            for game in games
        ],
        "teams": teams,
        "trends": rank_slate_trends(enriched, limit=limit, unavailable=ruled_out),
        "balance": gap_balance(enriched, unavailable=ruled_out),
        "totals": {
            "games": len(games),
            "props_priced": len(enriched),
            "props_ruled_out": sum(
                1 for prop in enriched if int(prop["player_id"]) in ruled_out
            ),
            "players_out": sum(len(team["out"]) for team in teams.values()),
            "lines_recorded": len(totals),
            "average_total": round(sum(totals) / len(totals), 1) if totals else None,
        },
    }
