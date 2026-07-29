"""Shared row/frame builders for the feature-layer unit tests.

A plain module rather than a conftest: these are constructors, not pytest
fixtures, and calling them explicitly keeps each test's input visible in
the test itself.

Rows are hand-built rather than loaded, because the most valuable tests
here feed the pipeline data a correct database could never produce -- a
standings snapshot captured after the game it is joined to, a rolling
window that includes its own row. A fixture that sanitised its input
would make those tests pass for the wrong reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.frame import FeatureFrame, Row

SEASON = 2025
AS_OF = datetime(2025, 8, 1, tzinfo=UTC)
FIRST_TIP = datetime(2025, 6, 1, 23, 0, tzinfo=UTC)

TEAM_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "season_type",
    "start_time",
    "team_id",
    "team_abbrev",
    "team_is_franchise",
    "opponent_team_id",
    "opponent_abbrev",
    "opponent_is_franchise",
    "is_home",
    "points_scored",
    "points_allowed",
    "pace",
)


def context(**overrides: object) -> FeatureContext:
    fields: dict[str, object] = {"as_of": AS_OF, "seasons": (SEASON,)}
    fields.update(overrides)
    return FeatureContext(**fields)  # type: ignore[arg-type]


def team_row(
    *,
    game_id: int,
    team_id: int,
    start_time: datetime,
    points_scored: int = 80,
    points_allowed: int = 70,
    pace: float | None = 95.0,
    season: int = SEASON,
    season_type: str = "regular-season",
    is_home: bool = True,
    team_is_franchise: bool = True,
    opponent_is_franchise: bool = True,
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "season": season,
        "season_type": season_type,
        "start_time": start_time,
        "team_id": team_id,
        "team_abbrev": f"T{team_id}",
        "team_is_franchise": team_is_franchise,
        "opponent_team_id": 999,
        "opponent_abbrev": "OPP",
        "opponent_is_franchise": opponent_is_franchise,
        "is_home": is_home,
        "points_scored": points_scored,
        "points_allowed": points_allowed,
        "pace": pace,
    }


def team_schedule(
    team_id: int = 1,
    *,
    count: int = 6,
    gap: timedelta = timedelta(days=3),
    scores: Sequence[int] | None = None,
) -> list[dict[str, object]]:
    """`count` games for one team, `gap` apart, oldest first."""
    return [
        team_row(
            game_id=index + 1,
            team_id=team_id,
            start_time=FIRST_TIP + gap * index,
            points_scored=scores[index] if scores else 80 + index,
        )
        for index in range(count)
    ]


def frame_of(rows: Sequence[Row], columns: tuple[str, ...] = TEAM_COLUMNS) -> FeatureFrame:
    """A frame declared exactly as LoadTeamGamesStep would declare one."""
    return FeatureFrame.from_rows(
        rows,
        columns=columns,
        as_of_columns=("start_time",),
        event_time_column="start_time",
    )
