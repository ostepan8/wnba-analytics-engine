"""Pure parser: balldontlie /wnba/v1/standings -> models.

Payload shape (verified live, GOAT tier): a single flat response -- top-level
keys are just {"data": [...]}, no "meta"/pagination wrapper (confirmed by
requesting a cursor param and getting the same shape back). This matches the
data being one row per team per season (~13 rows for the whole WNBA), the
same "no pagination needed" shape as fetch_plays.

data[] -> team{id, conference, city, name, full_name, abbreviation}, season,
conference, wins, losses, win_percentage, games_behind, home_record,
away_record, conference_record, playoff_seed. home_record/away_record/
conference_record are free-text "W-L" strings (e.g. "16-6"), not split
win/loss columns.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlTeamRef
from wnba_engine.models.standings import StandingsRow
from wnba_engine.parsing import (
    parse_float,
    parse_int,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_standings(payload: object) -> tuple[StandingsRow, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> StandingsRow:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)
    team = _parse_team(require_mapping(row, "team", PROVIDER, context), context)
    return StandingsRow(
        team=team,
        season=parse_int(require(row, "season", PROVIDER, context), PROVIDER, context),
        conference=require_str(row, "conference", PROVIDER, context),
        wins=parse_int(require(row, "wins", PROVIDER, context), PROVIDER, context),
        losses=parse_int(require(row, "losses", PROVIDER, context), PROVIDER, context),
        win_percentage=parse_float(
            require(row, "win_percentage", PROVIDER, context), PROVIDER, context
        ),
        games_behind=parse_float(
            require(row, "games_behind", PROVIDER, context), PROVIDER, context
        ),
        home_record=require_str(row, "home_record", PROVIDER, context),
        away_record=require_str(row, "away_record", PROVIDER, context),
        conference_record=require_str(row, "conference_record", PROVIDER, context),
        playoff_seed=parse_int(require(row, "playoff_seed", PROVIDER, context), PROVIDER, context),
    )


def _parse_team(team: Mapping[str, object], context: str) -> BdlTeamRef:
    team_context = f"{context}.team"
    return BdlTeamRef(
        external_id=str(require(team, "id", PROVIDER, team_context)),
        abbreviation=require_str(team, "abbreviation", PROVIDER, team_context),
    )
