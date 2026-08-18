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

from wnba_engine.analysis.availability import share_of, summarise_absences
from wnba_engine.analysis.prop_trends import (
    attach_trends,
    group_history,
    opponents_in_game,
)
from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo, betting_repo, form_repo

router = APIRouter(tags=["trends"])

LIVE_MAX_AGE = 120
SEASON_MAX_AGE = 900


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
    opponent_of = opponents_in_game(
        by_player,
        home_team_id=game.get("home_team_id"),
        away_team_id=game.get("away_team_id"),
    )
    enriched = attach_trends(props, history=by_player, opponent_of=opponent_of)

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
    impact = form_repo.fetch_injury_impact(conn, [home_id, away_id], season=season)
    defense = _defense_ranked(conn, season=season)

    def side(team_id: int) -> dict[str, object]:
        team_form = dict(form.get(team_id) or {})
        last_game = team_form.get("last_game_at")
        # Days of rest, which is a real driver of scoring and is otherwise
        # invisible on a scoreboard.
        rest_days = None
        if last_game is not None:
            rest_days = max((game["start_time"] - last_game).days, 0)

        # What is missing, not just who. Three out is the same headline for
        # three bench players as for a 34-minute leading scorer.
        impact_rows = [dict(row) for row in impact.get(team_id, [])]
        # How long, not just whether -- a player out 25 games ago is already
        # priced into this team's recent form; one who just went down is not.
        player_ids = [int(row["player_id"]) for row in impact_rows]
        missed = form_repo.fetch_games_missed(conn, team_id, player_ids, season=season)
        empty_streak = {"streak": 0, "window_missed": 0, "window_size": 0}
        for row in impact_rows:
            streak = missed.get(int(row["player_id"]), empty_streak)
            row["games_missed"] = streak["streak"]
            row["recent_missed"] = streak["window_missed"]
            row["recent_window"] = streak["window_size"]
        absences = summarise_absences(impact_rows)
        points_for = team_form.get("points_for")
        for name in ("out", "at_risk"):
            absences[name]["share_of_points"] = share_of(
                absences[name]["points"], points_for
            )

        return {
            "team_id": team_id,
            "form": team_form,
            "rest_days": rest_days,
            "betting": betting_repo.fetch_team_betting_record(conn, team_id, season=season),
            "injuries": [row for row in injuries if row.get("team_id") == team_id],
            "absences": absences,
            "defense": [row for row in defense if row["team_id"] == team_id],
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
    rows = _defense_ranked(conn, season=resolved)
    if team_id is not None:
        rows = [row for row in rows if row["team_id"] == team_id]
    return {"season": resolved, "rows": rows}


def _defense_ranked(conn: Connection, *, season: int) -> list[dict[str, object]]:
    """League-wide defence by position, each row carrying its rank.

    Ranked across the WHOLE league even when one team is being displayed: a raw
    "18.2 points allowed to guards" says nothing without knowing whether that is
    stingy or generous, and a rank computed within one team's own rows would
    just be that team sorted against itself.
    """
    rows = form_repo.fetch_defense_by_position(conn, season=season)
    by_position: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_position.setdefault(str(row["position"]), []).append(dict(row))
    for group in by_position.values():
        group.sort(key=lambda row: float(row["points_allowed"] or 0))  # type: ignore[arg-type]
        # The league mean for the position, so a chart can show where the middle
        # is. A rank alone says which end of the league a team sits at, not how
        # far from ordinary it actually is.
        values = [float(row["points_allowed"] or 0) for row in group]
        average = round(sum(values) / len(values), 1) if values else None
        for rank, row in enumerate(group, start=1):
            row["points_allowed_rank"] = rank
            row["teams_ranked"] = len(group)
            row["points_allowed_league_avg"] = average
    return [row for group in by_position.values() for row in group]
