"""Pure parser: balldontlie /wnba/v1/games -> BdlGameMatchup.

Only extracts what's needed to match a balldontlie game to our canonical
game via entity_repo.find_game_id_by_teams (team full names + date) -- not
scores/status, which ESPN already owns (see 0001_canonical_entities.sql).
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.balldontlie_games import BdlGameMatchup
from wnba_engine.parsing import (
    parse_datetime_utc,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_games(payload: object) -> tuple[BdlGameMatchup, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_game(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_game(row: object, context: str) -> BdlGameMatchup:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    home = require_mapping(row, "home_team", PROVIDER, context)
    away = require_mapping(row, "visitor_team", PROVIDER, context)
    return BdlGameMatchup(
        external_id=str(require(row, "id", PROVIDER, context)),
        home_team_full_name=require_str(home, "full_name", PROVIDER, f"{context}.home_team"),
        away_team_full_name=require_str(away, "full_name", PROVIDER, f"{context}.visitor_team"),
        start_time=parse_datetime_utc(
            require(row, "date", PROVIDER, context), PROVIDER, f"{context}.date"
        ),
    )
