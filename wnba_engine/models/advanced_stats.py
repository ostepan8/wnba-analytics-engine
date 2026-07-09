"""Advanced per-player-per-game stats (currently balldontlie-only).

balldontlie identifies players/teams/games with its own numeric ids, a
different id space than ESPN's -- these refs carry balldontlie's raw
identity plus enough info (full name, team abbreviation) for the pipeline
to resolve them to our canonical entities via the same crosswalk ESPN's
data already populated, not a second parallel identity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BdlPlayerRef:
    external_id: str
    full_name: str
    position: str | None


@dataclass(frozen=True, slots=True)
class BdlTeamRef:
    external_id: str
    abbreviation: str


@dataclass(frozen=True, slots=True)
class BdlGameRef:
    external_id: str


@dataclass(frozen=True, slots=True)
class PlayerAdvancedStats:
    player: BdlPlayerRef
    team: BdlTeamRef
    game: BdlGameRef
    minutes: str | None

    offensive_rating: float | None
    defensive_rating: float | None
    net_rating: float | None
    pace: float | None
    possessions: int | None
    true_shooting_percentage: float | None
    effective_field_goal_percentage: float | None
    usage_percentage: float | None
    assist_percentage: float | None
    assist_ratio: float | None
    assist_to_turnover: float | None
    turnover_ratio: float | None
    rebound_percentage: float | None
    offensive_rebound_percentage: float | None
    defensive_rebound_percentage: float | None
    pie: float | None

    free_throw_attempt_rate: float | None
    team_turnover_percentage: float | None
    opp_effective_field_goal_percentage: float | None
    opp_free_throw_attempt_rate: float | None
    opp_team_turnover_percentage: float | None
    opp_offensive_rebound_percentage: float | None

    misc_stats: dict[str, object]
    usage_stats: dict[str, object]
    scoring_stats: dict[str, object]
