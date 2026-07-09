"""Pure parser: balldontlie /wnba/v1/plays -> BdlPlay.

Payload shape (verified live, GOAT tier): data[] -> game_id (scalar, not
nested like advanced-stats' "game" object), order, type, text, home_score,
away_score, period, clock, scoring_play, score_value, team{id,
abbreviation, ...}. No player field -- see models/plays.py.

"text" and "team" are both sometimes absent: "ejection" plays (verified
live, 2026 season) carry text: null and no "team" key at all.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.advanced_stats import BdlGameRef, BdlTeamRef
from wnba_engine.models.plays import BdlPlay
from wnba_engine.parsing import (
    optional_int,
    parse_int,
    require,
    require_sequence,
    require_str,
)

PROVIDER = "balldontlie"


def parse_plays(payload: object) -> tuple[BdlPlay, ...]:
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    rows = require_sequence(payload, "data", PROVIDER, "$")
    return tuple(_parse_row(row, f"data[{i}]") for i, row in enumerate(rows))


def _parse_row(row: object, context: str) -> BdlPlay:
    if not isinstance(row, Mapping):
        raise ProviderValidationError(PROVIDER, "row must be an object", context=context)

    team_raw = row.get("team")
    team = _parse_team(team_raw, context) if isinstance(team_raw, Mapping) else None

    clock = row.get("clock")
    description = row.get("text")
    return BdlPlay(
        game=BdlGameRef(external_id=str(require(row, "game_id", PROVIDER, context))),
        team=team,
        sequence=parse_int(require(row, "order", PROVIDER, context), PROVIDER, context),
        period=parse_int(require(row, "period", PROVIDER, context), PROVIDER, context),
        clock=clock if isinstance(clock, str) and clock.strip() else None,
        play_type=require_str(row, "type", PROVIDER, context),
        description=description if isinstance(description, str) and description.strip() else None,
        home_score=parse_int(require(row, "home_score", PROVIDER, context), PROVIDER, context),
        away_score=parse_int(require(row, "away_score", PROVIDER, context), PROVIDER, context),
        scoring_play=bool(row.get("scoring_play", False)),
        score_value=optional_int(row.get("score_value"), PROVIDER, context) or 0,
    )


def _parse_team(team: Mapping[str, object], context: str) -> BdlTeamRef:
    team_context = f"{context}.team"
    return BdlTeamRef(
        external_id=str(require(team, "id", PROVIDER, team_context)),
        abbreviation=require_str(team, "abbreviation", PROVIDER, team_context),
    )
