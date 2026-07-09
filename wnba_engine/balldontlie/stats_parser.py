"""Pure parser: balldontlie /wnba/v1/player_stats and /wnba/v1/team_stats
-> models.

These are balldontlie's TRADITIONAL box score stats (points/rebounds/
assists/etc.) -- a different endpoint from player_game_advanced_stats /
team_game_advanced_stats (offensive rating, PIE, four factors; see
advanced_stats_parser.py / team_advanced_stats_parser.py). ESPN already
ingests traditional box scores; this exists purely to give a SECOND,
independent source of the same counting stats for future cross-source
validation, not to replace ESPN.

Payload shape (verified live, GOAT tier):
  player_stats: data[] -> player{id, first_name, last_name, position,
    position_abbreviation, height, weight, jersey_number, college, age},
    team{id, conference, city, name, full_name, abbreviation},
    game{id, date, season}, min, fgm, fga, fg3m, fg3a, ftm, fta, oreb,
    dreb, reb, ast, stl, blk, turnover, pf, pts, plus_minus
  team_stats: data[] -> team{...same shape...}, game{...same shape...},
    fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct, oreb, dreb,
    reb, ast, stl, blk, turnovers, fouls

Two real data-quality quirks discovered live (100-row live samples), both
on player_stats only -- team_stats fields were never null in the same
samples:

1. No `starter` field at all, unlike ESPN's box scores. Every parsed row
   gets starter=False; there is no way to recover this from balldontlie's
   traditional stats endpoint.
2. `min` is a reliable did-not-play signal (did_not_play := min == "0"),
   but a player who DID log minutes can still have every counting stat
   come back null (e.g. a real live row: min="2", fgm=null, fga=1) --
   garbage-time appearances balldontlie apparently doesn't fully record.
   Each counting stat is parsed independently via optional_int, so a
   played row can still carry a mix of real numbers and nulls.
   Shooting pairs (fgm/fga, fg3m/fg3a, ftm/fta) are a stricter case: made
   and attempted come back null independently of each other (verified
   live: 16/100 rows had fgm null while fga was populated). Since
   ShootingLine requires both fields, a pair with either side null is
   treated as a fully untracked line (None) -- same convention ESPN's own
   '--' placeholder already uses in wnba_engine/espn/parser.py, rather
   than fabricating a zero for the missing side.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from wnba_engine.balldontlie.player_ref_parsing import parse_player_ref
from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlGameRef, BdlPlayerRef, BdlTeamRef
from wnba_engine.models.box_scores import PlayerBoxLine, PlayerRef, ShootingLine, TeamBoxScore
from wnba_engine.models.games import TeamRef
from wnba_engine.parsing import (
    optional_int,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


@dataclass(frozen=True, slots=True)
class PlayerStatRow:
    """One parsed /wnba/v1/player_stats row: balldontlie identity refs
    (for crosswalk resolution) plus the box line itself."""

    player: BdlPlayerRef
    team: BdlTeamRef
    game: BdlGameRef
    box: PlayerBoxLine


@dataclass(frozen=True, slots=True)
class TeamStatRow:
    """One parsed /wnba/v1/team_stats row."""

    team: BdlTeamRef
    game: BdlGameRef
    box: TeamBoxScore


def parse_player_stats(payload: object) -> tuple[PlayerStatRow, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_player_row(row, f"data[{i}]") for i, row in enumerate(rows))


def parse_team_stats(payload: object) -> tuple[TeamStatRow, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_team_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_player_row(row: object, context: str) -> PlayerStatRow:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)

    player_mapping = require_mapping(row, "player", PROVIDER, context)
    bdl_player = parse_player_ref(player_mapping, f"{context}.player")
    team_mapping = require_mapping(row, "team", PROVIDER, context)
    bdl_team, team_ref = _parse_team_refs(team_mapping, context)
    game = _parse_game(require_mapping(row, "game", PROVIDER, context), context)

    raw_minutes = optional_int(row.get("min"), PROVIDER, f"{context}.min")
    did_not_play = raw_minutes is None or raw_minutes == 0
    # Match ESPN's did-not-play convention (see espn/parser.py::_empty_line):
    # a did-not-play row's minutes goes to None, not the literal 0
    # balldontlie's min="0" would otherwise produce.
    minutes = None if did_not_play else raw_minutes

    box = PlayerBoxLine(
        player=PlayerRef(
            external_id=bdl_player.external_id,
            full_name=bdl_player.full_name,
            position=bdl_player.position,
        ),
        team=team_ref,
        # balldontlie's traditional stats endpoint carries no starter flag
        # (verified live) -- see module docstring.
        starter=False,
        did_not_play=did_not_play,
        minutes=minutes,
        points=optional_int(row.get("pts"), PROVIDER, f"{context}.pts"),
        field_goals=_optional_shooting_line(
            row.get("fgm"), row.get("fga"), PROVIDER, f"{context}.fg"
        ),
        three_pointers=_optional_shooting_line(
            row.get("fg3m"), row.get("fg3a"), PROVIDER, f"{context}.fg3"
        ),
        free_throws=_optional_shooting_line(
            row.get("ftm"), row.get("fta"), PROVIDER, f"{context}.ft"
        ),
        rebounds=optional_int(row.get("reb"), PROVIDER, f"{context}.reb"),
        offensive_rebounds=optional_int(row.get("oreb"), PROVIDER, f"{context}.oreb"),
        defensive_rebounds=optional_int(row.get("dreb"), PROVIDER, f"{context}.dreb"),
        assists=optional_int(row.get("ast"), PROVIDER, f"{context}.ast"),
        steals=optional_int(row.get("stl"), PROVIDER, f"{context}.stl"),
        blocks=optional_int(row.get("blk"), PROVIDER, f"{context}.blk"),
        turnovers=optional_int(row.get("turnover"), PROVIDER, f"{context}.turnover"),
        fouls=optional_int(row.get("pf"), PROVIDER, f"{context}.pf"),
        plus_minus=optional_int(row.get("plus_minus"), PROVIDER, f"{context}.plus_minus"),
    )
    return PlayerStatRow(player=bdl_player, team=bdl_team, game=game, box=box)


def _parse_team_row(row: object, context: str) -> TeamStatRow:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)

    team_mapping = require_mapping(row, "team", PROVIDER, context)
    bdl_team, team_ref = _parse_team_refs(team_mapping, context)
    game = _parse_game(require_mapping(row, "game", PROVIDER, context), context)

    box = TeamBoxScore(
        team=team_ref,
        field_goals=ShootingLine(
            made=_require_int(row, "fgm", context),
            attempted=_require_int(row, "fga", context),
        ),
        three_pointers=ShootingLine(
            made=_require_int(row, "fg3m", context),
            attempted=_require_int(row, "fg3a", context),
        ),
        free_throws=ShootingLine(
            made=_require_int(row, "ftm", context),
            attempted=_require_int(row, "fta", context),
        ),
        rebounds=_require_int(row, "reb", context),
        offensive_rebounds=_require_int(row, "oreb", context),
        defensive_rebounds=_require_int(row, "dreb", context),
        assists=_require_int(row, "ast", context),
        steals=_require_int(row, "stl", context),
        blocks=_require_int(row, "blk", context),
        turnovers=_require_int(row, "turnovers", context),
        fouls=_require_int(row, "fouls", context),
    )
    return TeamStatRow(team=bdl_team, game=game, box=box)


def _parse_team_refs(team: Mapping[str, object], context: str) -> tuple[BdlTeamRef, TeamRef]:
    team_context = f"{context}.team"
    external_id = str(require(team, "id", PROVIDER, team_context))
    abbreviation = require_str(team, "abbreviation", PROVIDER, team_context)
    full_name = require_str(team, "full_name", PROVIDER, team_context)
    bdl_team = BdlTeamRef(external_id=external_id, abbreviation=abbreviation)
    team_ref = TeamRef(external_id=external_id, name=full_name, abbreviation=abbreviation)
    return bdl_team, team_ref


def _parse_game(game: Mapping[str, object], context: str) -> BdlGameRef:
    game_context = f"{context}.game"
    return BdlGameRef(external_id=str(require(game, "id", PROVIDER, game_context)))


def _require_int(row: Mapping[str, object], key: str, context: str) -> int:
    value = require(row, key, PROVIDER, context)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            PROVIDER, f"key '{key}' must be an integer, got {value!r}", context=context
        ) from exc


def _optional_shooting_line(
    made: object, attempted: object, provider: str, context: str
) -> ShootingLine | None:
    made_int = optional_int(made, provider, f"{context}m")
    attempted_int = optional_int(attempted, provider, f"{context}a")
    if made_int is None or attempted_int is None:
        return None
    return ShootingLine(made=made_int, attempted=attempted_int)
