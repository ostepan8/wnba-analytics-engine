"""Shared parser for balldontlie's player-bio object.

Three balldontlie endpoints (player_game_advanced_stats,
player_shot_locations, and the /players sweep) each embed a player object
with an IDENTICAL field set -- id, first_name, last_name, position,
height, weight, jersey_number, college, age (verified live,
field-for-field) -- just nested at different depths: the first two nest it
under row["player"], while the /players endpoint's row IS the player
object. Centralized here so all three parsers share one implementation
instead of three copy-pasted versions.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.models.advanced_stats import BdlPlayerRef
from wnba_engine.parsing import optional_int, optional_str, require, require_str

PROVIDER = "balldontlie"


def parse_player_ref(player: Mapping[str, object], context: str) -> BdlPlayerRef:
    """Parse one balldontlie player-bio object into a BdlPlayerRef.

    `context` must already point at the player object itself (e.g.
    "data[0].player" for the nested-under-a-row shape, or "data[0]" for
    the /players endpoint's flat shape).
    """
    external_id = str(require(player, "id", PROVIDER, context))
    first_name = require_str(player, "first_name", PROVIDER, context)
    last_name = require_str(player, "last_name", PROVIDER, context)
    position = player.get("position")
    return BdlPlayerRef(
        external_id=external_id,
        full_name=f"{first_name} {last_name}",
        position=position if isinstance(position, str) and position else None,
        height=optional_str(player.get("height"), PROVIDER, context),
        weight=optional_str(player.get("weight"), PROVIDER, context),
        jersey_number=optional_str(player.get("jersey_number"), PROVIDER, context),
        college=optional_str(player.get("college"), PROVIDER, context),
        age=optional_int(player.get("age"), PROVIDER, context),
    )
