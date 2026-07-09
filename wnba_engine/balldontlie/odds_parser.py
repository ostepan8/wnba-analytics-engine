"""Pure parser: balldontlie /wnba/v1/odds -> models.GameOddsRow.

Payload shape (verified live, GOAT tier): cursor-paginated, same
{"data": [...], "meta": {"per_page": ..., "next_cursor": ...}} envelope as
the other cursor-paginated balldontlie endpoints. Confirmed the query
contract is `dates[]=YYYY-MM-DD` (or `game_ids[]=<int>`) -- a bare `date=`
param 400s with "At least one of dates or game_ids is required".

Also confirmed live: this endpoint only carries a ROLLING RECENT WINDOW of
games (the current/upcoming season), not full historical archives -- every
2025-season date and game_id tried returned a valid empty `{"data": []}`,
while 2026-season (current) dates returned real rows. See
wnba_engine/pipeline/balldontlie_odds_ingest.py for how the backfill command
accounts for this.

data[] -> id, game_id, vendor, spread_home_value/spread_home_odds,
spread_away_value/spread_away_odds, moneyline_home_odds/moneyline_away_odds,
total_value/total_over_odds/total_under_odds, updated_at. spread/total
*_value fields are free-text numeric strings (e.g. "8.5", "-9.5"), not JSON
numbers -- same "numeric-as-string" shape balldontlie uses elsewhere
(win_percentage, home_record).
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.odds import GameOddsRow
from wnba_engine.parsing import (
    optional_float,
    optional_int,
    parse_datetime_utc,
    require,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_game_odds(payload: object) -> tuple[GameOddsRow, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> GameOddsRow:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    return GameOddsRow(
        external_id=str(require(row, "id", PROVIDER, context)),
        game_external_id=str(require(row, "game_id", PROVIDER, context)),
        vendor=require_str(row, "vendor", PROVIDER, context),
        spread_home_value=optional_float(row.get("spread_home_value"), PROVIDER, context),
        spread_home_odds=optional_int(row.get("spread_home_odds"), PROVIDER, context),
        spread_away_value=optional_float(row.get("spread_away_value"), PROVIDER, context),
        spread_away_odds=optional_int(row.get("spread_away_odds"), PROVIDER, context),
        moneyline_home_odds=optional_int(row.get("moneyline_home_odds"), PROVIDER, context),
        moneyline_away_odds=optional_int(row.get("moneyline_away_odds"), PROVIDER, context),
        total_value=optional_float(row.get("total_value"), PROVIDER, context),
        total_over_odds=optional_int(row.get("total_over_odds"), PROVIDER, context),
        total_under_odds=optional_int(row.get("total_under_odds"), PROVIDER, context),
        updated_at=parse_datetime_utc(
            require(row, "updated_at", PROVIDER, context), PROVIDER, context
        ),
    )
