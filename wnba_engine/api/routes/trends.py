"""Live prop lines with how often each has actually been cleared.

The research view: a market says "over 24.5 points"; this answers how often this
player has gone past 24.5 in her last five, ten and twenty games, against this
opponent, at home and away.

Descriptive, and deliberately not more than that. A hit rate is the past
frequency of an outcome, not a forecast, and MODELING_FINDINGS.md records that
no forecasting edge has been produced from this data. Small windows are noise;
every rate ships with its denominator and a window under four decided games
returns counts and no percentage at all.

Read-only. There is no order placement anywhere in this codebase (ROADMAP.md
non-goals).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import Connection

from wnba_engine.analysis.prop_trends import group_history, trends_for_line
from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo, betting_repo, form_repo

router = APIRouter(tags=["trends"])

LIVE_MAX_AGE = 120
SEASON_MAX_AGE = 900

# Prop market -> the box-score column it settles against.
STAT_BY_PROP = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes": "three_pointers_made",
    "points_rebounds_assists": "points_rebounds_assists",
}


def _season(season: int | None) -> int:
    return season or datetime.now(UTC).year


@router.get("/games/{game_id}/trends")
def game_prop_trends(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Every live prop for this game, each with the player's record against it.

    The history window is cut at this game's tip-off, so a completed game is
    previewed with what was known BEFORE it -- not with its own result folded
    in, which would show a perfect record and look like insight.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_MAX_AGE}"

    game = analytics_repo.fetch_game(conn, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"no game with id {game_id}")

    props = betting_repo.fetch_market_props(conn, game_id=game_id, limit=500)
    if not props:
        return {"game_id": game_id, "props": [], "count": 0}

    player_ids = sorted({int(prop["player_id"]) for prop in props})
    # Scoped to THIS game's season. Unscoped, the window labelled "Season"
    # counted a whole career -- 237 games for a five-year player -- which is a
    # different claim wearing the same label.
    history = form_repo.fetch_player_stat_history(
        conn,
        player_ids,
        before=str(game["start_time"]),
        season=int(game["season"]) if game.get("season") else None,
    )
    by_player = group_history(history)

    # Which side of THIS game each player is on, taken from the team she most
    # recently played for. The history row carries her own team_id, so this is a
    # direct read rather than an inference from the opponent.
    home_id = game.get("home_team_id")
    away_id = game.get("away_team_id")
    opponent_of: dict[int, int | None] = {}
    for player_id, rows in by_player.items():
        own_team = rows[0].get("team_id") if rows else None
        if own_team == home_id:
            opponent_of[player_id] = away_id
        elif own_team == away_id:
            opponent_of[player_id] = home_id
        else:
            # She has not appeared for either side this season (a trade, or no
            # games yet). No opponent window rather than a wrong one.
            opponent_of[player_id] = None

    enriched = []
    for prop in props:
        stat_key = STAT_BY_PROP.get(str(prop["prop_type"]))
        if stat_key is None:
            continue
        player_id = int(prop["player_id"])
        rows = by_player.get(player_id, [])

        enriched.append(
            {
                **prop,
                **trends_for_line(
                    rows,
                    stat_key=stat_key,
                    line=float(prop["line"]),
                    opponent_team_id=opponent_of.get(player_id),
                ),
            }
        )

    return {"game_id": game_id, "props": enriched, "count": len(enriched)}


@router.get("/games/{game_id}/matchup")
def game_matchup(
    game_id: int,
    response: Response,
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Both sides of a game in one call: record, form, scoring, rest, betting
    record and the current injury report.

    Everything is cut at this game's tip-off, so previewing a completed game
    shows what was known beforehand rather than a record that already contains
    its result.

    One request rather than eight. A scoreboard renders several games at once
    and a call per team per statistic would be dozens of round trips for a
    single screen.
    """
    response.headers["Cache-Control"] = f"public, max-age={LIVE_MAX_AGE}"

    game = analytics_repo.fetch_game(conn, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"no game with id {game_id}")

    season = int(game["season"])
    home_id = int(game["home_team_id"])
    away_id = int(game["away_team_id"])
    tip = str(game["start_time"])

    form = form_repo.fetch_team_form(conn, [home_id, away_id], season=season, before=tip)
    injuries = form_repo.fetch_current_injuries(conn, [home_id, away_id])

    def side(team_id: int) -> dict[str, object]:
        team_form = dict(form.get(team_id) or {})
        last_game = team_form.get("last_game_at")
        # Days of rest, which is a real driver of scoring and is otherwise
        # invisible on a scoreboard.
        rest_days = None
        if last_game is not None:
            rest_days = max((game["start_time"] - last_game).days, 0)
        return {
            "team_id": team_id,
            "form": team_form,
            "rest_days": rest_days,
            "betting": betting_repo.fetch_team_betting_record(conn, team_id, season=season),
            "injuries": [row for row in injuries if row.get("team_id") == team_id],
        }

    return {
        "game_id": game_id,
        "season": season,
        "home": side(home_id),
        "away": side(away_id),
    }


@router.get("/teams/{team_a}/head-to-head/{team_b}")
def head_to_head(
    team_a: int,
    team_b: int,
    response: Response,
    limit: int = Query(10, ge=1, le=50),
    before: str | None = Query(
        None,
        description="Only meetings before this timestamp — pass the previewed game's tip-off.",
    ),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Previous meetings between two teams, newest first.

    `before` matters. Without it, previewing a completed game lists that game
    itself as prior history, so its own result appears as evidence about
    itself — the same leak the trend windows are cut to avoid.
    """
    response.headers["Cache-Control"] = f"public, max-age={SEASON_MAX_AGE}"
    meetings = form_repo.fetch_head_to_head(
        conn, team_a, team_b, before=before, limit=limit
    )

    def team_a_won(game: dict) -> bool:
        home, away = game["home_score"] or 0, game["away_score"] or 0
        if game["home_team_id"] == team_a:
            return home > away
        return away > home

    wins_a = sum(1 for game in meetings if team_a_won(game))
    return {
        "team_a": team_a,
        "team_b": team_b,
        "meetings": meetings,
        "played": len(meetings),
        "wins_a": wins_a,
        "wins_b": len(meetings) - wins_a,
    }


@router.get("/defense/by-position")
def defense_by_position(
    response: Response,
    season: int | None = Query(None, ge=1997, le=2100),
    team_id: int | None = Query(None),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """What each team allows to each position, per opposing player-game.

    Averaged per player-game rather than summed: a team that has simply played
    more games would otherwise look like a worse defence.
    """
    response.headers["Cache-Control"] = f"public, max-age={SEASON_MAX_AGE}"
    resolved = _season(season)
    rows = form_repo.fetch_defense_by_position(conn, season=resolved, team_id=team_id)

    # A raw "18.2 points allowed to guards" says nothing without knowing whether
    # that is good, so each row carries its league rank within its position.
    by_position: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_position.setdefault(str(row["position"]), []).append(dict(row))
    for group in by_position.values():
        group.sort(key=lambda row: float(row["points_allowed"] or 0))
        for rank, row in enumerate(group, start=1):
            row["points_allowed_rank"] = rank
            row["teams_ranked"] = len(group)

    return {
        "season": resolved,
        "rows": [row for group in by_position.values() for row in group],
    }
