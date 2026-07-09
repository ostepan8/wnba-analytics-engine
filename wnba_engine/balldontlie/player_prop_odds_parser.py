"""Pure parser: balldontlie /wnba/v1/odds/player_props -> models.PlayerPropOddsRow.

Payload shape (verified live, GOAT tier): same cursor-paginated
{"data": [...], "meta": {...}} envelope as /wnba/v1/odds, but a DIFFERENT
query contract -- this endpoint requires a single `game_id=<int>` (not
`dates[]`/`game_ids[]`); a bare request or a `dates[]` param 400s with
"game_id must be an integer". See wnba_engine/pipeline/
balldontlie_player_prop_odds_ingest.py for how the backfill command
accounts for this.

data[] -> id, game_id, player_id, vendor, prop_type, line_value, market,
updated_at. `player_id` is balldontlie's own numeric player id -- the same
id space /wnba/v1/players and the advanced-stats/shot-zone endpoints use
(verified live: querying /wnba/v1/players?player_ids[]=468 for a player_id
seen here returns "Breanna Stewart", matching balldontlie's regular player
id space) -- so resolution is a straight provider_entity_map lookup, not a
name-based match (this payload carries no player name at all).

`market` is a nested object, not flat fields, and its shape depends on
`market.type` (verified live, both seen in the same response):
  - {"type": "milestone", "odds": <int>}
  - {"type": "over_under", "over_odds": <int>, "under_odds": <int>}
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.odds import PlayerPropOddsRow
from wnba_engine.parsing import (
    optional_int,
    parse_datetime_utc,
    parse_float,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_player_prop_odds(payload: object) -> tuple[PlayerPropOddsRow, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> PlayerPropOddsRow:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    market = require_mapping(row, "market", PROVIDER, context)
    market_type = require_str(market, "type", PROVIDER, f"{context}.market")
    odds, over_odds, under_odds = _parse_market_odds(market, market_type, f"{context}.market")
    return PlayerPropOddsRow(
        external_id=str(require(row, "id", PROVIDER, context)),
        game_external_id=str(require(row, "game_id", PROVIDER, context)),
        player_external_id=str(require(row, "player_id", PROVIDER, context)),
        vendor=require_str(row, "vendor", PROVIDER, context),
        prop_type=require_str(row, "prop_type", PROVIDER, context),
        line_value=parse_float(require(row, "line_value", PROVIDER, context), PROVIDER, context),
        market_type=market_type,
        odds=odds,
        over_odds=over_odds,
        under_odds=under_odds,
        updated_at=parse_datetime_utc(
            require(row, "updated_at", PROVIDER, context), PROVIDER, context
        ),
    )


def _parse_market_odds(
    market: Mapping[str, object], market_type: str, context: str
) -> tuple[int | None, int | None, int | None]:
    """Returns (odds, over_odds, under_odds) -- exactly one pair is
    populated depending on market_type, matching the payload's actual
    shape rather than inventing a value balldontlie never sent.
    """
    if market_type == "milestone":
        odds = optional_int(require(market, "odds", PROVIDER, context), PROVIDER, context)
        return odds, None, None
    if market_type == "over_under":
        return (
            None,
            optional_int(require(market, "over_odds", PROVIDER, context), PROVIDER, context),
            optional_int(require(market, "under_odds", PROVIDER, context), PROVIDER, context),
        )
    raise ProviderValidationError(PROVIDER, f"unknown market.type {market_type!r}", context=context)
