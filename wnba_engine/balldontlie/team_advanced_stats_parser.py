"""Pure parser: balldontlie /wnba/v1/team_game_advanced_stats -> models.

Payload shape (verified live, GOAT tier):
  data[] -> id, team{id, abbreviation, ...}, game{id, date, season}, period,
            stats{misc, usage, scoring, advanced, four_factors}

Same category shape as /wnba/v1/player_game_advanced_stats (see
advanced_stats_parser.py) -- no player dimension, since this is a team-level
aggregate for the whole game rather than one player's box score line.

advanced + four_factors are promoted to typed fields (see
models.advanced_stats.TeamAdvancedStats), using the SAME promoted-field set
as PlayerAdvancedStats even though the live team-level "advanced" category
has one extra field (estimated_team_turnover_percentage) the player-level
payload doesn't -- dropped for consistency with the "estimated_*" siblings
PlayerAdvancedStats already drops. misc, usage, scoring are kept as raw
dicts, same reasoning as the player-level parser.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlGameRef, BdlTeamRef, TeamAdvancedStats
from wnba_engine.parsing import (
    optional_float,
    optional_int,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_team_advanced_stats(payload: object) -> tuple[TeamAdvancedStats, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> TeamAdvancedStats:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)

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

    return TeamAdvancedStats(
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


def _parse_team(team: Mapping[str, object], context: str) -> BdlTeamRef:
    team_context = f"{context}.team"
    return BdlTeamRef(
        external_id=str(require(team, "id", PROVIDER, team_context)),
        abbreviation=require_str(team, "abbreviation", PROVIDER, team_context),
    )


def _parse_game(game: Mapping[str, object], context: str) -> BdlGameRef:
    game_context = f"{context}.game"
    return BdlGameRef(external_id=str(require(game, "id", PROVIDER, game_context)))
