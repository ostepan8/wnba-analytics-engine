"""Box score shapes: team totals and per-player lines for one game."""

from __future__ import annotations

from dataclasses import dataclass

from wnba_engine.models.games import TeamRef


@dataclass(frozen=True, slots=True)
class ShootingLine:
    """Made-attempted pair for a shot type (FG, 3PT, FT)."""

    made: int
    attempted: int


@dataclass(frozen=True, slots=True)
class TeamBoxScore:
    """One team's box score totals for one game."""

    team: TeamRef
    field_goals: ShootingLine
    three_pointers: ShootingLine
    free_throws: ShootingLine
    rebounds: int
    offensive_rebounds: int
    defensive_rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int


@dataclass(frozen=True, slots=True)
class PlayerRef:
    """A player as identified by one provider."""

    external_id: str
    full_name: str
    position: str | None


@dataclass(frozen=True, slots=True)
class PlayerBoxLine:
    """One player's stat line for one game.

    Stat fields are None for players who did not play.
    """

    player: PlayerRef
    team: TeamRef
    starter: bool
    did_not_play: bool
    minutes: int | None
    points: int | None
    field_goals: ShootingLine | None
    three_pointers: ShootingLine | None
    free_throws: ShootingLine | None
    rebounds: int | None
    offensive_rebounds: int | None
    defensive_rebounds: int | None
    assists: int | None
    steals: int | None
    blocks: int | None
    turnovers: int | None
    fouls: int | None
    plus_minus: int | None


@dataclass(frozen=True, slots=True)
class GameBoxScore:
    """Full box score for one game: two team totals + all player lines."""

    game_external_id: str
    teams: tuple[TeamBoxScore, ...]
    players: tuple[PlayerBoxLine, ...]
