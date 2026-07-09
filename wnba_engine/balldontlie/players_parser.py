"""Pure parser: balldontlie /wnba/v1/players -> models.

Payload shape (verified live, GOAT tier): data[] -> id, first_name,
last_name, position, position_abbreviation, height, weight, jersey_number,
college, age, team{id, conference, city, name, full_name, abbreviation}.

The bio field set (id/first_name/last_name/position/height/weight/
jersey_number/college/age) is IDENTICAL to the nested player{} object
already parsed by advanced_stats_parser and shot_zone_parser -- see
player_ref_parsing.parse_player_ref, shared by all three. The only
difference here is shape, not fields: this endpoint's row IS the player
object (no row["player"] wrapper), and `team` here is the player's current
roster team rather than a game-context team -- not consumed by this parser
since resolve_or_create_player_by_name has no team parameter.

Unlike player_game_advanced_stats/player_shot_locations (scoped to a
season), this endpoint returns EVERY player balldontlie has ever recorded
regardless of season or recent game activity (859 total, verified live) --
that's the whole point of the sweep: backfilling bio data for players who
never appear in the other two payload types.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.balldontlie.player_ref_parsing import parse_player_ref
from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlPlayerRef
from wnba_engine.parsing import require_sequence

PROVIDER = "balldontlie"


def parse_players(payload: object) -> tuple[BdlPlayerRef, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> BdlPlayerRef:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    return parse_player_ref(row, context)
