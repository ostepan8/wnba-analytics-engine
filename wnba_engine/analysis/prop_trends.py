"""How often a player has actually cleared a line.

A price says "over 24.5 points". What a reader needs to weigh it is how often
this player has gone past 24.5 recently, and against this opponent. That is what
this computes -- descriptively, from games already played.

Three rules it does not bend:

**Point-in-time.** Windows are built only from games finished BEFORE the game in
question. A "last 5" that includes the game being previewed manufactures a
perfect record and is invisible in the output.

**A rate never travels without its denominator.** 4-of-5 and 40-of-50 are
different claims. Every window carries `games`, and a window with too few games
returns a count rather than a rate at all.

**A push is not a hit.** Whole-number prop lines make exact ties common, and
counting them as overs inflates every rate on the page.

What this is NOT: a prediction, or a recommendation. A hit rate is the past
frequency of an outcome, and this project's own MODELING_FINDINGS.md records
that no forecasting edge has been produced from this data -- including that
blanket prop strategies lose once graded at takeable prices. Five games is
noise; the sample sizes are shown so that stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Below this a window reports its counts but not a percentage: three games is
# not a rate, and rendering "66.7%" from 2-of-3 invites exactly the
# over-reading this whole codebase argues against.
MIN_GAMES_FOR_RATE = 4

# The windows a reader actually asks for.
WINDOWS = (5, 10, 20)

# Which box-score column each prop market settles against. A market this does
# not name is skipped rather than guessed at -- grading a prop against the wrong
# column produces a confident number that is simply about something else.
STAT_BY_PROP = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes": "three_pointers_made",
    "points_rebounds_assists": "points_rebounds_assists",
}


@dataclass(frozen=True, slots=True)
class Window:
    label: str
    games: int
    overs: int
    unders: int
    pushes: int
    average: float | None

    @property
    def decided(self) -> int:
        return self.overs + self.unders

    @property
    def rate(self) -> float | None:
        """None when the sample is too small to express as a percentage."""
        if self.decided < MIN_GAMES_FOR_RATE:
            return None
        return self.overs / self.decided

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "games": self.games,
            "overs": self.overs,
            "unders": self.unders,
            "pushes": self.pushes,
            "average": None if self.average is None else round(self.average, 1),
            "rate": None if self.rate is None else round(self.rate, 3),
        }


def summarise(values: list[float], line: float, label: str) -> Window:
    """Count a list of per-game values against a line."""
    overs = sum(1 for value in values if value > line)
    unders = sum(1 for value in values if value < line)
    pushes = sum(1 for value in values if value == line)
    average = sum(values) / len(values) if values else None
    return Window(
        label=label,
        games=len(values),
        overs=overs,
        unders=unders,
        pushes=pushes,
        average=average,
    )


def trends_for_line(
    history: list[dict[str, Any]],
    *,
    stat_key: str,
    line: float,
    opponent_team_id: int | None = None,
) -> dict[str, Any]:
    """Windows for one player against one line.

    `history` must already be that player's games, newest first, and must
    already exclude the game being previewed -- this function does not know
    which game that is and cannot enforce it.
    """
    values = [
        float(row[stat_key])
        for row in history
        if row.get(stat_key) is not None
    ]

    windows = [summarise(values[:size], line, f"L{size}") for size in WINDOWS]
    windows.append(summarise(values, line, "Season"))

    if opponent_team_id is not None:
        against = [
            float(row[stat_key])
            for row in history
            if row.get(stat_key) is not None
            and row.get("opponent_team_id") == opponent_team_id
        ]
        windows.append(summarise(against, line, "vs opp"))

    home = [
        float(row[stat_key])
        for row in history
        if row.get(stat_key) is not None and row.get("is_home")
    ]
    away = [
        float(row[stat_key])
        for row in history
        if row.get(stat_key) is not None and row.get("is_home") is False
    ]
    windows.append(summarise(home, line, "Home"))
    windows.append(summarise(away, line, "Away"))

    return {
        "line": line,
        "windows": [window.as_dict() for window in windows],
        # The most recent games, so a reader can see the run rather than trust
        # a summary of it.
        "recent": [
            {
                "game_id": row["game_id"],
                "start_time": row["start_time"],
                "value": row[stat_key],
                "opponent_team_id": row.get("opponent_team_id"),
                "is_home": row.get("is_home"),
                "cleared": None
                if row[stat_key] is None
                else (
                    "over" if float(row[stat_key]) > line
                    else "under" if float(row[stat_key]) < line
                    else "push"
                ),
            }
            for row in history[: max(WINDOWS)]
            if row.get(stat_key) is not None
        ],
    }


def opponents_in_game(
    history: dict[int, list[dict[str, Any]]],
    *,
    home_team_id: int | None,
    away_team_id: int | None,
) -> dict[int, int | None]:
    """Which side of a game each player is on, and so who she faces.

    Taken from the team she most recently played for, which the history row
    already carries -- a direct read rather than an inference. A player who has
    appeared for neither side this season (a trade, or no games yet) gets no
    opponent window rather than a wrong one.
    """
    opponent_of: dict[int, int | None] = {}
    for player_id, rows in history.items():
        own_team = rows[0].get("team_id") if rows else None
        if own_team == home_team_id:
            opponent_of[player_id] = away_team_id
        elif own_team == away_team_id:
            opponent_of[player_id] = home_team_id
        else:
            opponent_of[player_id] = None
    return opponent_of


def attach_trends(
    props: list[dict[str, Any]],
    *,
    history: dict[int, list[dict[str, Any]]],
    opponent_of: dict[int, int | None],
) -> list[dict[str, Any]]:
    """Pair each prop with the player's record against its line.

    Pure: the caller supplies the history, already cut to games before the one
    being previewed. Props whose market has no box-score column are dropped.
    """
    enriched: list[dict[str, Any]] = []
    for prop in props:
        stat_key = STAT_BY_PROP.get(str(prop["prop_type"]))
        if stat_key is None:
            continue
        player_id = int(prop["player_id"])
        enriched.append(
            {
                **prop,
                **trends_for_line(
                    history.get(player_id, []),
                    stat_key=stat_key,
                    line=float(prop["line"]),
                    opponent_team_id=opponent_of.get(player_id),
                ),
            }
        )
    return enriched


def group_history(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Split a multi-player history into per-player lists, newest first.

    The query returns players interleaved; sorting per player here keeps the
    "newest first" contract that every window above depends on.
    """
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["player_id"]), []).append(row)
    for history in grouped.values():
        history.sort(key=lambda row: row["start_time"], reverse=True)
    return grouped
