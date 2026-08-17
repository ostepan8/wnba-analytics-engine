"""the-odds-api HTTP client. Paid API (high-quota plan) -- authenticates via
a query-string `apiKey=` parameter, NOT a header (unlike balldontlie) --
verified live. That means the key can end up embedded in httpx's own
exception messages (which include the full request URL) and in this
client's request-failure logging, so every call here goes through
JsonHttpClient's redact_query_param_keys -- see wnba_engine/http_client.py.
Never log/print settings.odds_api_key directly in this module either.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "the_odds_api"
SPORT_KEY = "basketball_wnba"
ODDS_PATH = f"v4/sports/{SPORT_KEY}/odds/"
HISTORICAL_ODDS_PATH = f"v4/historical/sports/{SPORT_KEY}/odds/"
SCORES_PATH = f"v4/sports/{SPORT_KEY}/scores/"

# Player props live on the per-EVENT odds endpoints only -- the bulk
# /odds path above cannot return them at any market list.
EVENTS_PATH = f"v4/sports/{SPORT_KEY}/events/"
HISTORICAL_EVENTS_PATH = f"v4/historical/sports/{SPORT_KEY}/events/"
EVENT_ODDS_PATH = f"v4/sports/{SPORT_KEY}/events/{{event_id}}/odds/"
HISTORICAL_EVENT_ODDS_PATH = f"v4/historical/sports/{SPORT_KEY}/events/{{event_id}}/odds/"

# A per-event historical request 404s when that event id wasn't listed at
# the requested timestamp -- a real answer ("not listed yet"), not a
# failure. See fetch_historical_event_props.
EVENT_ABSENT_STATUSES = frozenset({404})


def _format_date(at: datetime) -> str:
    """the-odds-api's `date` param wants second-precision ISO8601 with a
    literal Z, not an offset -- shared by every historical endpoint."""
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


# Confirmed live: the default (no oddsFormat) is decimal odds (e.g. 1.14),
# which does NOT fit sportsbook_game_odds' American-odds INT columns.
ODDS_FORMAT = "american"
REGIONS = "us"
MARKETS = "h2h,spreads,totals"

# the-odds-api charges [markets] x [regions] credits per request, so this list
# costs 1 credit where MARKETS costs 3.
#
# The forward divergence log reads exactly two columns from the book side --
# moneyline_home_odds and moneyline_away_odds (wnba_engine/pipeline/
# divergence_log.py) -- so the pre-tip capture that feeds it was paying triple
# for spreads and totals it never looks at. The 2-hourly routine snapshot still
# takes all three markets; those columns matter to the wider dataset, just not
# to this experiment, and they do not need a two-minute cadence.
MONEYLINE_ONLY_MARKETS = "h2h"


class OddsApiClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.odds_api_key:
            # Fail fast at construction, not on the first request -- same
            # convention as BalldontlieClient.
            raise ValueError(
                "WNBA_ENGINE_ODDS_API_KEY is not set -- the-odds-api has no "
                "free/anonymous tier for this data."
            )
        self._api_key = settings.odds_api_key
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.odds_api_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.odds_api_min_request_interval_seconds,
            redact_query_param_keys=frozenset({"apiKey"}),
        )

    def _base_params(self, markets: str = MARKETS) -> dict[str, object]:
        return {
            "apiKey": self._api_key,
            "regions": REGIONS,
            "markets": markets,
            "oddsFormat": ODDS_FORMAT,
        }

    def fetch_current_odds(self, *, markets: str = MARKETS) -> object:
        """GET /v4/sports/basketball_wnba/odds/ -- every currently-listed
        WNBA event's odds in a single response (verified live: no
        pagination on this endpoint -- small enough event count that none
        is needed).

        `markets` is a cost lever, not a preference. the-odds-api prices a
        request at [markets] x [regions], so the default three-market list
        costs 3 credits per call where a single market costs 1. The
        high-frequency pre-tip capture passes H2H_ONLY for exactly that
        reason -- see MONEYLINE_ONLY_MARKETS."""
        return self._http.get_json(ODDS_PATH, params=self._base_params(markets))

    def fetch_historical_odds(self, at: datetime) -> object:
        """GET /v4/historical/sports/basketball_wnba/odds/?date=<ISO8601>
        -- the nearest actual snapshot AT OR BEFORE `at` (verified live:
        the `date` param is not exact -- the response's own `timestamp`
        field says what was actually returned). Costs 10x a current-odds
        call per the `x-requests-last` header (verified live: 30 vs 3 for
        the same market set) -- callers should budget quota accordingly
        for a checkpoint sweep across many games."""
        params = self._base_params()
        params["date"] = _format_date(at)
        return self._http.get_json(HISTORICAL_ODDS_PATH, params=params)

    def fetch_events(self) -> object:
        """GET /v4/sports/basketball_wnba/events/ -- currently-listed events
        with id/teams/commence_time but NO odds. Costs 0 quota (verified
        live via x-requests-last), which is what makes the per-event props
        sweep affordable: discover ids for free, then pay only for the
        events actually wanted."""
        return self._http.get_json(EVENTS_PATH, params={"apiKey": self._api_key})

    def fetch_historical_events(self, at: datetime) -> object:
        """GET /v4/historical/sports/basketball_wnba/events/?date=<ISO8601>
        -- the event list as it stood at `at`. Needed because a historical
        props call is per-EVENT and the-odds-api's event ids are not stable
        for a game's whole life (see DATA_INVENTORY.md), so the id valid at
        one checkpoint may not be the id valid at another."""
        return self._http.get_json(
            HISTORICAL_EVENTS_PATH,
            params={"apiKey": self._api_key, "date": _format_date(at)},
        )

    def fetch_event_props(self, event_id: str, *, markets: Sequence[str]) -> object:
        """GET /v4/sports/basketball_wnba/events/{eventId}/odds/ -- player
        props for ONE event.

        Props are unavailable on the bulk /odds endpoint; this per-event
        call is the only way to get them. Costs 1 quota unit per market per
        region (verified live: x-requests-last was 1 for one market, 3 for
        three), so a five-market sweep is 5 units per event.
        """
        return self._http.get_json(
            EVENT_ODDS_PATH.format(event_id=event_id),
            params={**self._base_params(), "markets": ",".join(markets)},
        )

    def fetch_historical_event_props(
        self, event_id: str, at: datetime, *, markets: Sequence[str]
    ) -> object | None:
        """GET /v4/historical/sports/basketball_wnba/events/{eventId}/odds/
        ?date=<ISO8601> -- historical player props for ONE event at one
        checkpoint. Returns None when the event did not exist at `at`.

        That None case is the normal one, not an edge case: an event id is
        only valid for the window the-odds-api actually listed that event,
        and the endpoint returns 404 outside it (verified live -- a T-7d
        checkpoint 404s for a game the provider only posted 3 days out).
        Treating that as "no props at this checkpoint" is what lets a
        season-long sweep run to completion instead of dying on the first
        game whose line went up late.

        Costs 10 quota units per market per region (verified live:
        x-requests-last was 10 for one market, 30 for three) -- 10x the
        current-props call, same multiplier as the game-odds historical
        endpoint. A five-market, four-checkpoint sweep is therefore 200
        units per game; budget accordingly before ranging over a season.
        """
        return self._http.get_json_optional(
            HISTORICAL_EVENT_ODDS_PATH.format(event_id=event_id),
            params={
                **self._base_params(),
                "markets": ",".join(markets),
                "date": _format_date(at),
            },
            absent_statuses=EVENT_ABSENT_STATUSES,
        )

    def fetch_scores(self, *, days_from: int) -> object:
        """GET /v4/sports/basketball_wnba/scores/?daysFrom=N -- completed
        AND not-yet-final events from the trailing `days_from` days in one
        response (verified live, max observed useful range docs say up to
        3). Not apiKey-only -- markets/regions/oddsFormat don't apply here
        (this endpoint has no odds, only final scores)."""
        return self._http.get_json(
            SCORES_PATH, params={"apiKey": self._api_key, "daysFrom": days_from}
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OddsApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
