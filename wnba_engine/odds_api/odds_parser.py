"""Pure parser: the-odds-api /v4/sports/basketball_wnba/odds (current) and
/v4/historical/sports/basketball_wnba/odds (historical) -> models.GameOddsRow.

Reuses the SAME GameOddsRow dataclass balldontlie's odds parser produces
(see wnba_engine/models/odds.py) -- both providers' payloads reduce to the
identical moneyline/spread/total shape once requested in American odds
format (oddsFormat=american; the-odds-api's default is decimal, which would
NOT fit sportsbook_game_odds' INT columns -- verified live).

Payload shape (verified live, regions=us, markets=h2h,spreads,totals,
oddsFormat=american):
  - Current odds: a bare JSON array of events.
  - Historical odds: {timestamp, previous_timestamp, next_timestamp,
    data: [...same event shape as current odds...]}.
Each event: {id, sport_key, sport_title, commence_time, home_team,
away_team, bookmakers: [{key, title, last_update, markets: [{key,
last_update, outcomes: [{name, price, point?}]}]}]}. `home_team`/
`away_team` are full team names (e.g. "Atlanta Dream"), matching this
repo's canonical team naming.

external_id: unlike balldontlie (whose /odds gives each bookmaker-row its
own numeric id), the-odds-api's `id` is per-EVENT, shared by every
bookmaker quoting that event. Using the bare event id as
sportsbook_game_odds.external_id would let a second bookmaker's row for the
same event silently collide under UNIQUE(external_id, captured_at) if two
bookmakers happened to share the same last_update timestamp (low
probability given sub-second precision, but a real data-loss risk, not
just a idempotency wrinkle). So external_id here is `f"{event_id}:
{vendor}"` -- still rooted in the-odds-api's own event id (satisfying "one
odds row per bookmaker per event, traceable back to the source event"),
but unique per bookmaker within that event.

captured_at is the BOOKMAKER-level `last_update` (not each individual
market's own last_update, and not our ingest wall-clock) -- one row per
bookmaker combines that bookmaker's h2h/spreads/totals markets, so one
timestamp per row is the natural fit, mirroring balldontlie's
updated_at-as-captured_at convention.

Unknown/extra market keys (e.g. 'alternate_spreads') are ignored, not
errors -- forward-compatible with the-odds-api adding new market types
this schema has no column for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.odds import GameOddsRow
from wnba_engine.models.odds_api_events import OddsApiEventRef, ParsedOddsEvent
from wnba_engine.parsing import (
    parse_datetime_utc,
    parse_float,
    parse_int,
    require,
    require_sequence,
    require_str,
)

PROVIDER = "the_odds_api"

MARKET_H2H = "h2h"
MARKET_SPREADS = "spreads"
MARKET_TOTALS = "totals"
OUTCOME_OVER = "Over"
OUTCOME_UNDER = "Under"


def parse_current_odds(payload: object) -> tuple[GameOddsRow, ...]:
    """GET /v4/sports/basketball_wnba/odds/ -- a bare array of events.
    Flattened rows only; use parse_current_odds_events when the caller also
    needs each event's home_team/away_team/commence_time to resolve a
    canonical game (see wnba_engine/pipeline/odds_api_ingest.py)."""
    return tuple(row for parsed in parse_current_odds_events(payload) for row in parsed.rows)


def parse_historical_odds(payload: object) -> tuple[GameOddsRow, ...]:
    """GET /v4/historical/sports/basketball_wnba/odds/ -- flattened rows
    only; see parse_current_odds' docstring for why
    parse_historical_odds_events exists alongside this."""
    return tuple(row for parsed in parse_historical_odds_events(payload) for row in parsed.rows)


def parse_current_odds_events(payload: object) -> tuple[ParsedOddsEvent, ...]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, f"payload must be a list, got {type(payload).__name__}", context="$"
        )
    return _parse_events(payload, "$")


def parse_historical_odds_events(payload: object) -> tuple[ParsedOddsEvent, ...]:
    """Events live under payload["data"], alongside timestamp/
    previous_timestamp/next_timestamp metadata this parser doesn't need
    (the caller already knows what checkpoint timestamp it asked for)."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}", context="$"
        )
    events = require_sequence(payload, "data", PROVIDER, "$")
    return _parse_events(events, "$.data")


def _parse_events(events: Sequence[object], context: str) -> tuple[ParsedOddsEvent, ...]:
    return tuple(_parse_event(event, f"{context}[{i}]") for i, event in enumerate(events))


def _parse_event(event: object, context: str) -> ParsedOddsEvent:
    if not isinstance(event, Mapping):
        raise ProviderValidationError(PROVIDER, "event must be an object", context=context)
    event_id = require_str(event, "id", PROVIDER, context)
    home_team = require_str(event, "home_team", PROVIDER, context)
    away_team = require_str(event, "away_team", PROVIDER, context)
    commence_time = parse_datetime_utc(
        require(event, "commence_time", PROVIDER, context), PROVIDER, context
    )
    event_ref = OddsApiEventRef(
        external_id=event_id,
        home_team=home_team,
        away_team=away_team,
        commence_time=commence_time,
    )

    bookmakers = event.get("bookmakers")
    if bookmakers is None:
        # A brand-new event the-odds-api hasn't posted any book on yet --
        # legitimate, not malformed (verified: never observed live, but
        # the field isn't documented as required on every event). The
        # event is still worth resolving to a canonical game now, even
        # with zero odds rows to persist yet.
        return ParsedOddsEvent(event=event_ref, rows=())
    if not isinstance(bookmakers, Sequence) or isinstance(bookmakers, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, "bookmakers must be a list", context=f"{context}.bookmakers"
        )
    rows = tuple(
        _parse_bookmaker(bookmaker, event_id, home_team, away_team, f"{context}.bookmakers[{i}]")
        for i, bookmaker in enumerate(bookmakers)
    )
    return ParsedOddsEvent(event=event_ref, rows=rows)


def _parse_bookmaker(
    bookmaker: object, event_id: str, home_team: str, away_team: str, context: str
) -> GameOddsRow:
    if not isinstance(bookmaker, Mapping):
        raise ProviderValidationError(PROVIDER, "bookmaker must be an object", context=context)
    vendor = require_str(bookmaker, "key", PROVIDER, context)
    updated_at = parse_datetime_utc(
        require(bookmaker, "last_update", PROVIDER, context), PROVIDER, context
    )
    markets = require_sequence(bookmaker, "markets", PROVIDER, context)

    spread_home_value: float | None = None
    spread_home_odds: int | None = None
    spread_away_value: float | None = None
    spread_away_odds: int | None = None
    moneyline_home_odds: int | None = None
    moneyline_away_odds: int | None = None
    total_value: float | None = None
    total_over_odds: int | None = None
    total_under_odds: int | None = None

    for j, market in enumerate(markets):
        market_context = f"{context}.markets[{j}]"
        if not isinstance(market, Mapping):
            raise ProviderValidationError(
                PROVIDER, "market must be an object", context=market_context
            )
        key = require_str(market, "key", PROVIDER, market_context)
        outcomes = require_sequence(market, "outcomes", PROVIDER, market_context)

        if key == MARKET_H2H:
            for k, outcome in enumerate(outcomes):
                name, price = _parse_outcome(outcome, f"{market_context}.outcomes[{k}]")
                if name == home_team:
                    moneyline_home_odds = price
                elif name == away_team:
                    moneyline_away_odds = price
        elif key == MARKET_SPREADS:
            for k, outcome in enumerate(outcomes):
                name, price, point = _parse_outcome_with_point(
                    outcome, f"{market_context}.outcomes[{k}]"
                )
                if name == home_team:
                    spread_home_value, spread_home_odds = point, price
                elif name == away_team:
                    spread_away_value, spread_away_odds = point, price
        elif key == MARKET_TOTALS:
            for k, outcome in enumerate(outcomes):
                name, price, point = _parse_outcome_with_point(
                    outcome, f"{market_context}.outcomes[{k}]"
                )
                if name == OUTCOME_OVER:
                    total_value, total_over_odds = point, price
                elif name == OUTCOME_UNDER:
                    total_under_odds = price
                    if total_value is None:
                        total_value = point
        # else: unknown market key -- ignored, see module docstring.

    return GameOddsRow(
        external_id=f"{event_id}:{vendor}",
        game_external_id=event_id,
        vendor=vendor,
        spread_home_value=spread_home_value,
        spread_home_odds=spread_home_odds,
        spread_away_value=spread_away_value,
        spread_away_odds=spread_away_odds,
        moneyline_home_odds=moneyline_home_odds,
        moneyline_away_odds=moneyline_away_odds,
        total_value=total_value,
        total_over_odds=total_over_odds,
        total_under_odds=total_under_odds,
        updated_at=updated_at,
    )


def _parse_outcome(outcome: object, context: str) -> tuple[str, int]:
    if not isinstance(outcome, Mapping):
        raise ProviderValidationError(PROVIDER, "outcome must be an object", context=context)
    name = require_str(outcome, "name", PROVIDER, context)
    price = parse_int(require(outcome, "price", PROVIDER, context), PROVIDER, context)
    return name, price


def _parse_outcome_with_point(outcome: object, context: str) -> tuple[str, int, float]:
    name, price = _parse_outcome(outcome, context)
    point = parse_float(require(outcome, "point", PROVIDER, context), PROVIDER, context)
    return name, price, point
