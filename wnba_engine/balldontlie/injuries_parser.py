"""Pure parser: balldontlie /wnba/v1/player_injuries -> models.

Payload shape (verified live, GOAT tier): data[] -> player{id, first_name,
last_name, position, position_abbreviation, height, weight,
jersey_number, college, age, team{id, conference, city, name, full_name,
abbreviation}}, status, return_date, comment. Cursor-paginated
(meta.next_cursor), same contract as the other cursor-paginated
balldontlie endpoints -- though a real full-league sweep (43 rows,
verified live) fits on a single page well under per_page=100.

Unlike player_ref_parsing.parse_player_ref's shared player object (which
never carries a nested team -- see that module's docstring), this
endpoint's player object DOES nest a full team, so the team is parsed
here rather than by the shared helper.

status has no structured type code here (ESPN's status_type, e.g.
"INJURY_STATUS_OUT", has no balldontlie equivalent -- verified against the
OpenAPI spec and live responses: only status/return_date/comment).
return_date is left as raw text rather than parsed into a date -- it's a
bare "Mon D" string with no year (e.g. "Jul 9"), the same ambiguity ESPN's
Wayback backfill has to infer a year for; inferring one here would be a
guess this parser has no basis for making.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from wnba_engine.balldontlie.player_ref_parsing import parse_player_ref
from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlTeamRef
from wnba_engine.models.balldontlie_injuries import BdlInjuryEntry
from wnba_engine.parsing import (
    optional_str,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_injuries(payload: object, *, captured_at: datetime) -> tuple[BdlInjuryEntry, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]", captured_at) for i, row in enumerate(rows))


def _parse_row(row: object, context: str, captured_at: datetime) -> BdlInjuryEntry:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    player_context = f"{context}.player"
    player_obj = require_mapping(row, "player", PROVIDER, context)
    player = parse_player_ref(player_obj, player_context)
    team = _parse_team(
        require_mapping(player_obj, "team", PROVIDER, player_context), player_context
    )
    return BdlInjuryEntry(
        player=player,
        team=team,
        status=require_str(row, "status", PROVIDER, context),
        return_date_text=optional_str(row.get("return_date"), PROVIDER, context),
        comment=optional_str(row.get("comment"), PROVIDER, context),
        captured_at=captured_at,
    )


def _parse_team(team: Mapping[str, object], context: str) -> BdlTeamRef:
    team_context = f"{context}.team"
    return BdlTeamRef(
        external_id=str(require(team, "id", PROVIDER, team_context)),
        abbreviation=require_str(team, "abbreviation", PROVIDER, team_context),
    )
