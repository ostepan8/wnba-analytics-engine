"""Pure parser: balldontlie /wnba/v1/player_game_advanced_stats -> models.

Payload shape (verified live, GOAT tier):
  data[] -> id, player{id, first_name, last_name, position, team{...}},
            team{id, abbreviation, ...} (game-context team, NOT the same as
            player.team -- that's the player's current roster team, which
            can differ after a trade), game{id, date, season}, period,
            stats{misc, usage, scoring, advanced, four_factors}

advanced + four_factors are promoted to typed fields (see models); misc,
usage, scoring are kept as raw dicts (real data, not worth ~40 more
dedicated columns for splits unlikely to be queried directly).
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import (
    BdlGameRef,
    BdlPlayerRef,
    BdlTeamRef,
    PlayerAdvancedStats,
)
from wnba_engine.parsing import (
    optional_float,
    optional_int,
    optional_str,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_player_advanced_stats(payload: object) -> tuple[PlayerAdvancedStats, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> PlayerAdvancedStats:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)

    player = _parse_player(require_mapping(row, "player", PROVIDER, context), context)
    team = _parse_team(require_mapping(row, "team", PROVIDER, context), context)
    game = _parse_game(require_mapping(row, "game", PROVIDER, context), context)

    stats = require_mapping(row, "stats", PROVIDER, context)
    advanced = require_mapping(stats, "advanced", PROVIDER, f"{context}.stats")
    four_factors = require_mapping(stats, "four_factors", PROVIDER, f"{context}.stats")
    misc = stats.get("misc")
    usage = stats.get("usage")
    scoring = stats.get("scoring")

    def adv(key: str) -> object:
        return advanced.get(key)

    def ff(key: str) -> object:
        return four_factors.get(key)

    return PlayerAdvancedStats(
        player=player,
        team=team,
        game=game,
        minutes=advanced.get("minutes") if isinstance(advanced.get("minutes"), str) else None,
        offensive_rating=optional_float(adv("offensive_rating"), PROVIDER, f"{context}.advanced"),
        defensive_rating=optional_float(adv("defensive_rating"), PROVIDER, f"{context}.advanced"),
        net_rating=optional_float(adv("net_rating"), PROVIDER, f"{context}.advanced"),
        pace=optional_float(adv("pace"), PROVIDER, f"{context}.advanced"),
        possessions=optional_int(adv("possessions"), PROVIDER, f"{context}.advanced"),
        true_shooting_percentage=optional_float(
            adv("true_shooting_percentage"), PROVIDER, f"{context}.advanced"
        ),
        effective_field_goal_percentage=optional_float(
            adv("effective_field_goal_percentage"), PROVIDER, f"{context}.advanced"
        ),
        usage_percentage=optional_float(adv("usage_percentage"), PROVIDER, f"{context}.advanced"),
        assist_percentage=optional_float(adv("assist_percentage"), PROVIDER, f"{context}.advanced"),
        assist_ratio=optional_float(adv("assist_ratio"), PROVIDER, f"{context}.advanced"),
        assist_to_turnover=optional_float(
            adv("assist_to_turnover"), PROVIDER, f"{context}.advanced"
        ),
        turnover_ratio=optional_float(adv("turnover_ratio"), PROVIDER, f"{context}.advanced"),
        rebound_percentage=optional_float(
            adv("rebound_percentage"), PROVIDER, f"{context}.advanced"
        ),
        offensive_rebound_percentage=optional_float(
            adv("offensive_rebound_percentage"), PROVIDER, f"{context}.advanced"
        ),
        defensive_rebound_percentage=optional_float(
            adv("defensive_rebound_percentage"), PROVIDER, f"{context}.advanced"
        ),
        pie=optional_float(adv("pie"), PROVIDER, f"{context}.advanced"),
        free_throw_attempt_rate=optional_float(
            ff("free_throw_attempt_rate"), PROVIDER, f"{context}.four_factors"
        ),
        team_turnover_percentage=optional_float(
            ff("team_turnover_percentage"), PROVIDER, f"{context}.four_factors"
        ),
        opp_effective_field_goal_percentage=optional_float(
            ff("opp_effective_field_goal_percentage"), PROVIDER, f"{context}.four_factors"
        ),
        opp_free_throw_attempt_rate=optional_float(
            ff("opp_free_throw_attempt_rate"), PROVIDER, f"{context}.four_factors"
        ),
        opp_team_turnover_percentage=optional_float(
            ff("opp_team_turnover_percentage"), PROVIDER, f"{context}.four_factors"
        ),
        opp_offensive_rebound_percentage=optional_float(
            ff("opp_offensive_rebound_percentage"), PROVIDER, f"{context}.four_factors"
        ),
        misc_stats=dict(misc) if isinstance(misc, Mapping) else {},
        usage_stats=dict(usage) if isinstance(usage, Mapping) else {},
        scoring_stats=dict(scoring) if isinstance(scoring, Mapping) else {},
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
        height=optional_str(player.get("height"), PROVIDER, player_context),
        weight=optional_str(player.get("weight"), PROVIDER, player_context),
        jersey_number=optional_str(player.get("jersey_number"), PROVIDER, player_context),
        college=optional_str(player.get("college"), PROVIDER, player_context),
        age=optional_int(player.get("age"), PROVIDER, player_context),
    )


def _parse_team(team: Mapping[str, object], context: str) -> BdlTeamRef:
    team_context = f"{context}.team"
    return BdlTeamRef(
        external_id=str(require(team, "id", PROVIDER, team_context)),
        abbreviation=require_str(team, "abbreviation", PROVIDER, team_context),
    )


def _parse_game(game: Mapping[str, object], context: str) -> BdlGameRef:
    game_context = f"{context}.game"
    return BdlGameRef(external_id=str(require(game, "id", PROVIDER, game_context)))
