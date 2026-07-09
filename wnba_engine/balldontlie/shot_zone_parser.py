"""Pure parser: balldontlie /wnba/v1/player_shot_locations and
/wnba/v1/team_shot_locations -> models.

Despite the endpoint names, this is season-level shot-zone efficiency
splits (8 fixed zones, field goals attempted/made), not per-shot x/y
coordinates -- balldontlie doesn't expose spatial shot data. See
models/shot_zones.py.

Payload shape (verified live, GOAT tier): data[] -> player{id, first_name,
last_name, position, team{...}} (player endpoint only), team{id,
abbreviation, ...}, season, season_type, stats.shot_zones.{zone}.{fga,fgm,fg_pct}.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlPlayerRef, BdlTeamRef
from wnba_engine.models.shot_zones import (
    PlayerShotZoneStats,
    ShotZoneBreakdown,
    ShotZoneCounts,
    TeamShotZoneStats,
)
from wnba_engine.parsing import (
    optional_int,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_player_shot_zone_stats(payload: object) -> tuple[PlayerShotZoneStats, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_player_row(row, f"data[{i}]") for i, row in enumerate(rows))


def parse_team_shot_zone_stats(payload: object) -> tuple[TeamShotZoneStats, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_team_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_player_row(row: object, context: str) -> PlayerShotZoneStats:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    player = _parse_player(require_mapping(row, "player", PROVIDER, context), context)
    team_raw = row.get("team")
    team = _parse_team(team_raw, context) if isinstance(team_raw, Mapping) else None
    return PlayerShotZoneStats(
        player=player,
        team=team,
        season=int(require(row, "season", PROVIDER, context)),
        season_type=require_str(row, "season_type", PROVIDER, context),
        zones=_parse_zones(row, context),
    )


def _parse_team_row(row: object, context: str) -> TeamShotZoneStats:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    team = _parse_team(require_mapping(row, "team", PROVIDER, context), context)
    return TeamShotZoneStats(
        team=team,
        season=int(require(row, "season", PROVIDER, context)),
        season_type=require_str(row, "season_type", PROVIDER, context),
        zones=_parse_zones(row, context),
    )


def _parse_zones(row: Mapping[str, object], context: str) -> ShotZoneBreakdown:
    stats = require_mapping(row, "stats", PROVIDER, context)
    shot_zones = require_mapping(stats, "shot_zones", PROVIDER, f"{context}.stats")
    zone_context = f"{context}.stats.shot_zones"
    return ShotZoneBreakdown(
        restricted_area=_parse_zone_counts(
            shot_zones.get("restricted_area"), f"{zone_context}.restricted_area"
        ),
        in_the_paint_non_ra=_parse_zone_counts(
            shot_zones.get("in_the_paint_non_ra"), f"{zone_context}.in_the_paint_non_ra"
        ),
        mid_range=_parse_zone_counts(shot_zones.get("mid_range"), f"{zone_context}.mid_range"),
        left_corner_3=_parse_zone_counts(
            shot_zones.get("left_corner_3"), f"{zone_context}.left_corner_3"
        ),
        right_corner_3=_parse_zone_counts(
            shot_zones.get("right_corner_3"), f"{zone_context}.right_corner_3"
        ),
        corner_3=_parse_zone_counts(shot_zones.get("corner_3"), f"{zone_context}.corner_3"),
        above_the_break_3=_parse_zone_counts(
            shot_zones.get("above_the_break_3"), f"{zone_context}.above_the_break_3"
        ),
        backcourt=_parse_zone_counts(shot_zones.get("backcourt"), f"{zone_context}.backcourt"),
    )


def _parse_zone_counts(zone: object, context: str) -> ShotZoneCounts:
    if not isinstance(zone, Mapping):
        return ShotZoneCounts(fga=None, fgm=None)
    return ShotZoneCounts(
        fga=optional_int(zone.get("fga"), PROVIDER, context),
        fgm=optional_int(zone.get("fgm"), PROVIDER, context),
    )


def _parse_player(player: Mapping[str, object], context: str) -> BdlPlayerRef:
    player_context = f"{context}.player"
    external_id = str(require(player, "id", PROVIDER, player_context))
    first_name = require_str(player, "first_name", PROVIDER, player_context)
    last_name = require_str(player, "last_name", PROVIDER, player_context)
    position = player.get("position")
    return BdlPlayerRef(
        external_id=external_id,
        full_name=f"{first_name} {last_name}",
        position=position if isinstance(position, str) and position else None,
    )


def _parse_team(team: Mapping[str, object], context: str) -> BdlTeamRef:
    team_context = f"{context}.team"
    return BdlTeamRef(
        external_id=str(require(team, "id", PROVIDER, team_context)),
        abbreviation=require_str(team, "abbreviation", PROVIDER, team_context),
    )
