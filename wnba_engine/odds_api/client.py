"""the-odds-api HTTP client. Paid API (high-quota plan) -- authenticates via
a query-string `apiKey=` parameter, NOT a header (unlike balldontlie) --
verified live. That means the key can end up embedded in httpx's own
exception messages (which include the full request URL) and in this
client's request-failure logging, so every call here goes through
JsonHttpClient's redact_query_param_keys -- see wnba_engine/http_client.py.
Never log/print settings.odds_api_key directly in this module either.
"""

from __future__ import annotations

from datetime import datetime

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "the_odds_api"
SPORT_KEY = "basketball_wnba"
ODDS_PATH = f"v4/sports/{SPORT_KEY}/odds/"
HISTORICAL_ODDS_PATH = f"v4/historical/sports/{SPORT_KEY}/odds/"
SCORES_PATH = f"v4/sports/{SPORT_KEY}/scores/"

# Confirmed live: the default (no oddsFormat) is decimal odds (e.g. 1.14),
# which does NOT fit sportsbook_game_odds' American-odds INT columns.
ODDS_FORMAT = "american"
REGIONS = "us"
MARKETS = "h2h,spreads,totals"


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

    def _base_params(self) -> dict[str, object]:
        return {
            "apiKey": self._api_key,
            "regions": REGIONS,
            "markets": MARKETS,
            "oddsFormat": ODDS_FORMAT,
        }

    def fetch_current_odds(self) -> object:
        """GET /v4/sports/basketball_wnba/odds/ -- every currently-listed
        WNBA event's odds in a single response (verified live: no
        pagination on this endpoint -- small enough event count that none
        is needed)."""
        return self._http.get_json(ODDS_PATH, params=self._base_params())

    def fetch_historical_odds(self, at: datetime) -> object:
        """GET /v4/historical/sports/basketball_wnba/odds/?date=<ISO8601>
        -- the nearest actual snapshot AT OR BEFORE `at` (verified live:
        the `date` param is not exact -- the response's own `timestamp`
        field says what was actually returned). Costs 10x a current-odds
        call per the `x-requests-last` header (verified live: 30 vs 3 for
        the same market set) -- callers should budget quota accordingly
        for a checkpoint sweep across many games."""
        params = self._base_params()
        params["date"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._http.get_json(HISTORICAL_ODDS_PATH, params=params)

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
