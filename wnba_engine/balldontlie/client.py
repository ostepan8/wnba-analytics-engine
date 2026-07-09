"""balldontlie HTTP client. Paid API (GOAT tier) -- Authorization header,
no anonymous access.
"""

from __future__ import annotations

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "balldontlie"
GAMES_PATH = "wnba/v1/games"
PLAYER_GAME_ADVANCED_STATS_PATH = "wnba/v1/player_game_advanced_stats"
DEFAULT_PAGE_SIZE = 100


class BalldontlieClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.balldontlie_api_key:
            # Fail fast at construction, not on the first request: there is
            # no free/anonymous tier for this data, so a missing key is a
            # configuration error to fix, not a transient failure to retry.
            raise ValueError(
                "WNBA_ENGINE_BALLDONTLIE_API_KEY is not set -- balldontlie has no "
                "free/anonymous tier for this data."
            )
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.balldontlie_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.balldontlie_min_request_interval_seconds,
            headers={"Authorization": settings.balldontlie_api_key},
        )

    def fetch_games_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/games -- one cursor-paginated page. home_team/
        visitor_team here (unlike player_game_advanced_stats' single
        game-context team) is what makes reliable team+date game matching
        possible."""
        params: dict[str, object] = {"seasons[]": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(GAMES_PATH, params=params)

    def fetch_player_advanced_stats_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/player_game_advanced_stats -- one cursor-paginated page."""
        params: dict[str, object] = {"seasons[]": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(PLAYER_GAME_ADVANCED_STATS_PATH, params=params)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BalldontlieClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
