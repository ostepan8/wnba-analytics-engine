"""Pure parser: the-odds-api /v4/sports/basketball_wnba/scores -> models.OddsApiGameScore.

Payload shape (verified live, ?daysFrom=N): a bare JSON array mixing
completed AND not-yet-started/in-progress events in the same response --
`completed: bool` and `scores: [{name, score}] | null` disambiguate.
Only completed games with a populated `scores` list produce a row; every
other event is silently skipped (not an error -- "not final yet" is the
normal, expected state for most rows in this window, not malformed data).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.odds_api_scores import OddsApiGameScore
from wnba_engine.parsing import parse_datetime_utc, parse_int, require, require_str

PROVIDER = "the_odds_api"


def parse_scores(payload: object) -> tuple[OddsApiGameScore, ...]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, f"payload must be a list, got {type(payload).__name__}", context="$"
        )
    rows: list[OddsApiGameScore] = []
    for i, event in enumerate(payload):
        row = _parse_event(event, f"$[{i}]")
        if row is not None:
            rows.append(row)
    return tuple(rows)


def _parse_event(event: object, context: str) -> OddsApiGameScore | None:
    if not isinstance(event, Mapping):
        raise ProviderValidationError(PROVIDER, "event must be an object", context=context)
    external_id = require_str(event, "id", PROVIDER, context)
    home_team = require_str(event, "home_team", PROVIDER, context)
    away_team = require_str(event, "away_team", PROVIDER, context)

    if not event.get("completed") or event.get("scores") is None:
        return None

    scores = event["scores"]
    if not isinstance(scores, Sequence) or isinstance(scores, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, "scores must be a list", context=f"{context}.scores"
        )

    home_score: int | None = None
    away_score: int | None = None
    for j, entry in enumerate(scores):
        entry_context = f"{context}.scores[{j}]"
        if not isinstance(entry, Mapping):
            raise ProviderValidationError(
                PROVIDER, "score entry must be an object", context=entry_context
            )
        name = require_str(entry, "name", PROVIDER, entry_context)
        score = parse_int(require(entry, "score", PROVIDER, entry_context), PROVIDER, entry_context)
        if name == home_team:
            home_score = score
        elif name == away_team:
            away_score = score
        else:
            raise ProviderValidationError(
                PROVIDER,
                f"score entry name {name!r} did not match home_team/away_team",
                context=entry_context,
            )

    if home_score is None or away_score is None:
        raise ProviderValidationError(
            PROVIDER,
            "scores list did not include both home_team and away_team entries",
            context=f"{context}.scores",
        )

    commence_time = parse_datetime_utc(
        require(event, "commence_time", PROVIDER, context), PROVIDER, context
    )
    captured_at = parse_datetime_utc(
        require(event, "last_update", PROVIDER, context), PROVIDER, context
    )
    return OddsApiGameScore(
        external_id=external_id,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        commence_time=commence_time,
        captured_at=captured_at,
    )
