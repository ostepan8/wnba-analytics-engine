"""Pure parser: the-odds-api EVENT-odds endpoints (current and historical)
-> models.PlayerPropOddsRow, carrying the player's name for the pipeline to
resolve.

Why a separate endpoint at all: player props are NOT available on the bulk
/v4/sports/{sport}/odds endpoint that wnba_engine/odds_api/odds_parser.py
consumes. They must be requested one event at a time from
/v4/sports/{sport}/events/{eventId}/odds (and its /v4/historical/...
counterpart) -- see wnba_engine/odds_api/client.py for the quota
consequences of that.

Payload shape (verified live, regions=us, oddsFormat=american):
  - Current:    a single event object.
  - Historical: {timestamp, previous_timestamp, next_timestamp, data: {
                 ...single event object... }}.
Note `data` here is a single OBJECT, not the ARRAY the bulk historical
odds endpoint returns -- the two historical shapes are genuinely
different, which is why this parser can't reuse the game-odds one.

Each event: {id, sport_key, sport_title, commence_time, home_team,
away_team, bookmakers: [{key, title, markets: [{key, last_update,
outcomes: [{name, description, point, price}]}]}]}, where per outcome:
  - `name`        is "Over" or "Under"
  - `description` is the PLAYER NAME (free text -- the only player
                  identifier that exists anywhere in the payload)
  - `point`       is the line
  - `price`       is American odds

captured_at is the MARKET-level `last_update`, deliberately not the
bookmaker-level one: verified live that the CURRENT event-odds response
omits `last_update` on the bookmaker entirely (keys are just key/title/
markets) while the HISTORICAL one includes it. Market-level `last_update`
is present in both and is strictly more precise anyway -- one prop market
can go stale while another on the same book keeps ticking.

Unknown/extra market keys are ignored rather than erroring, same
forward-compatibility stance as the game-odds parser.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.odds import PlayerPropOddsRow
from wnba_engine.models.odds_api_events import (
    OddsApiEventRef,
    OddsApiPropRow,
    ParsedPropEvent,
)
from wnba_engine.parsing import (
    parse_datetime_utc,
    parse_float,
    parse_int,
    require,
    require_sequence,
    require_str,
)

PROVIDER = "the_odds_api"

MARKET_PREFIX = "player_"
OUTCOME_OVER = "Over"
OUTCOME_UNDER = "Under"

# the-odds-api quotes both sides of every standard player prop, so these
# all land as balldontlie's "over_under" market_type rather than its
# single-sided "milestone" shape (see models/odds.py). Alternate-line
# markets ("player_points_alternate") are NOT requested -- they'd multiply
# quota cost and duplicate the same player at many lines.
MARKET_TYPE_OVER_UNDER = "over_under"

# The five markets this repo requests. Kept here rather than in the client
# so the parser's prop_type vocabulary and the request's market list can't
# drift apart.
REQUESTED_MARKETS: tuple[str, ...] = (
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_points_rebounds_assists",
)


def prop_type_for_market(market_key: str) -> str:
    """the-odds-api market key -> this repo's prop_type vocabulary.

    Stripping the "player_" prefix lands exactly on the values
    balldontlie's prop ingestion already writes ("points", "rebounds",
    "assists", "threes", "points_rebounds_assists"), which is the whole
    point: both providers' rows share one table, so a query filtering
    prop_type='points' must see both sources or the cross-source
    comparison this integration exists for silently misses half the data.
    """
    return market_key.removeprefix(MARKET_PREFIX)


def parse_current_event_props(payload: object) -> ParsedPropEvent:
    """GET /v4/sports/basketball_wnba/events/{eventId}/odds/ -- a single
    event object at the top level."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}", context="$"
        )
    return _parse_event(payload, "$")


def parse_historical_event_props(payload: object) -> ParsedPropEvent:
    """GET /v4/historical/sports/basketball_wnba/events/{eventId}/odds/ --
    the event object lives under "data" (a single object here, unlike the
    bulk historical odds endpoint's array)."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}", context="$"
        )
    data = require(payload, "data", PROVIDER, "$")
    if not isinstance(data, Mapping):
        raise ProviderValidationError(PROVIDER, "data must be an object", context="$.data")
    return _parse_event(data, "$.data")


def _parse_event(event: Mapping[str, object], context: str) -> ParsedPropEvent:
    event_ref = OddsApiEventRef(
        external_id=require_str(event, "id", PROVIDER, context),
        home_team=require_str(event, "home_team", PROVIDER, context),
        away_team=require_str(event, "away_team", PROVIDER, context),
        commence_time=parse_datetime_utc(
            require(event, "commence_time", PROVIDER, context), PROVIDER, context
        ),
    )

    bookmakers = event.get("bookmakers")
    if bookmakers is None:
        # No book has posted a prop on this event yet -- legitimate for a
        # freshly-listed game, and the event still resolves to a canonical
        # game. Same stance as the game-odds parser.
        return ParsedPropEvent(event=event_ref, props=())
    if not isinstance(bookmakers, Sequence) or isinstance(bookmakers, (str, bytes)):
        raise ProviderValidationError(
            PROVIDER, "bookmakers must be a list", context=f"{context}.bookmakers"
        )

    props: list[OddsApiPropRow] = []
    for i, bookmaker in enumerate(bookmakers):
        props.extend(
            _parse_bookmaker(bookmaker, event_ref.external_id, f"{context}.bookmakers[{i}]")
        )
    return ParsedPropEvent(event=event_ref, props=tuple(props))


def _parse_bookmaker(bookmaker: object, event_id: str, context: str) -> tuple[OddsApiPropRow, ...]:
    if not isinstance(bookmaker, Mapping):
        raise ProviderValidationError(PROVIDER, "bookmaker must be an object", context=context)
    vendor = require_str(bookmaker, "key", PROVIDER, context)
    markets = require_sequence(bookmaker, "markets", PROVIDER, context)

    rows: list[OddsApiPropRow] = []
    for j, market in enumerate(markets):
        rows.extend(_parse_market(market, event_id, vendor, f"{context}.markets[{j}]"))
    return tuple(rows)


def _parse_market(
    market: object, event_id: str, vendor: str, context: str
) -> tuple[OddsApiPropRow, ...]:
    if not isinstance(market, Mapping):
        raise ProviderValidationError(PROVIDER, "market must be an object", context=context)
    market_key = require_str(market, "key", PROVIDER, context)
    if not market_key.startswith(MARKET_PREFIX):
        return ()  # not a player prop (or an unknown key) -- ignored
    last_update = parse_datetime_utc(
        require(market, "last_update", PROVIDER, context), PROVIDER, context
    )
    outcomes = require_sequence(market, "outcomes", PROVIDER, context)
    prop_type = prop_type_for_market(market_key)

    # Over and Under arrive as two sibling outcomes sharing a player and a
    # line; they belong on ONE row (over_odds + under_odds), so group by
    # (player, line) before building rows. dict preserves insertion order,
    # keeping output order stable for tests.
    sides: dict[tuple[str, float], dict[str, int]] = {}
    for k, outcome in enumerate(outcomes):
        name, player, point, price = _parse_outcome(outcome, f"{context}.outcomes[{k}]")
        side_key = (player, point)
        sides.setdefault(side_key, {})
        if name == OUTCOME_OVER:
            sides[side_key]["over"] = price
        elif name == OUTCOME_UNDER:
            sides[side_key]["under"] = price
        # else: an unexpected third side -- ignored, same stance as an
        # unknown market key.

    return tuple(
        OddsApiPropRow(
            player_name=player,
            row=PlayerPropOddsRow(
                external_id=_prop_external_id(event_id, vendor, prop_type, player, point),
                game_external_id=event_id,
                # the-odds-api has no player id; the pipeline resolves
                # OddsApiPropRow.player_name instead. Carrying the name
                # here too keeps the row self-describing if it's ever
                # logged on a resolution failure.
                player_external_id=player,
                vendor=vendor,
                prop_type=prop_type,
                line_value=point,
                market_type=MARKET_TYPE_OVER_UNDER,
                odds=None,  # two-sided market -- see PlayerPropOddsRow docstring
                over_odds=prices.get("over"),
                under_odds=prices.get("under"),
                updated_at=last_update,
            ),
        )
        for (player, point), prices in sides.items()
    )


def _prop_external_id(event_id: str, vendor: str, prop_type: str, player: str, line: float) -> str:
    """Unique per (event, bookmaker, market, player, line).

    All five parts are load-bearing under sportsbook_player_prop_odds'
    UNIQUE(external_id, captured_at). One bookmaker quotes many players
    across many markets on a single event, so an id missing the player or
    the prop_type would collapse dozens of distinct rows onto one and
    silently drop them -- the same data-loss trap the game-odds parser
    documents for the bare event id. The LINE is included because a book
    can quote the same player and market at more than one number in a
    single response; without it those collide too.
    """
    return f"{event_id}:{vendor}:{prop_type}:{player}:{line}"


def _parse_outcome(outcome: object, context: str) -> tuple[str, str, float, int]:
    if not isinstance(outcome, Mapping):
        raise ProviderValidationError(PROVIDER, "outcome must be an object", context=context)
    name = require_str(outcome, "name", PROVIDER, context)
    player = require_str(outcome, "description", PROVIDER, context)
    point = parse_float(require(outcome, "point", PROVIDER, context), PROVIDER, context)
    price = parse_int(require(outcome, "price", PROVIDER, context), PROVIDER, context)
    return name, player, point, price


def latest_update(event: ParsedPropEvent) -> datetime | None:
    """Most recent market last_update across the event, or None if it has
    no props. Used only for logging/diagnostics."""
    return max((p.row.updated_at for p in event.props), default=None)
