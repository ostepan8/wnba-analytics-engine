"""balldontlie HTTP client. Paid API (GOAT tier) -- Authorization header,
no anonymous access.
"""

from __future__ import annotations

from datetime import date

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "balldontlie"
GAMES_PATH = "wnba/v1/games"
PLAYER_GAME_ADVANCED_STATS_PATH = "wnba/v1/player_game_advanced_stats"
TEAM_GAME_ADVANCED_STATS_PATH = "wnba/v1/team_game_advanced_stats"
PLAYS_PATH = "wnba/v1/plays"
PLAYER_SHOT_LOCATIONS_PATH = "wnba/v1/player_shot_locations"
TEAM_SHOT_LOCATIONS_PATH = "wnba/v1/team_shot_locations"
STANDINGS_PATH = "wnba/v1/standings"
ODDS_PATH = "wnba/v1/odds"
PLAYER_PROP_ODDS_PATH = "wnba/v1/odds/player_props"
PLAYERS_PATH = "wnba/v1/players"
PLAYER_STATS_PATH = "wnba/v1/player_stats"
TEAM_STATS_PATH = "wnba/v1/team_stats"
DEFAULT_PAGE_SIZE = 100
# A full 4-quarter game has ~440 plays (verified live); this ceiling gives
# OT games headroom while staying one request per game -- the endpoint
# isn't cursor-paginated (no meta.next_cursor in the response).
MAX_PLAYS_PER_GAME = 1000


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

    def fetch_team_advanced_stats_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/team_game_advanced_stats -- one cursor-paginated
        page. Same seasons[]/per_page/cursor contract as
        fetch_player_advanced_stats_page (verified live)."""
        params: dict[str, object] = {"seasons[]": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(TEAM_GAME_ADVANCED_STATS_PATH, params=params)

    def fetch_plays(self, game_id: int) -> object:
        """GET /wnba/v1/plays -- every play for one game in a single
        response (confirmed live: no cursor pagination on this endpoint,
        meta is absent from the response)."""
        return self._http.get_json(
            PLAYS_PATH, params={"game_id": game_id, "per_page": MAX_PLAYS_PER_GAME}
        )

    def fetch_player_shot_zone_stats_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/player_shot_locations -- one cursor-paginated page.
        Despite the name, this is season-level shot-zone efficiency splits
        (8 zones x fga/fgm), not per-shot x/y coordinates -- balldontlie
        doesn't expose spatial shot data."""
        params: dict[str, object] = {"season": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(PLAYER_SHOT_LOCATIONS_PATH, params=params)

    def fetch_team_shot_zone_stats_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/team_shot_locations -- one cursor-paginated page.
        Same season-level shot-zone shape as fetch_player_shot_zone_stats_page."""
        params: dict[str, object] = {"season": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(TEAM_SHOT_LOCATIONS_PATH, params=params)

    def fetch_standings(self, season: int) -> object:
        """GET /wnba/v1/standings -- every team's current standing for one
        season in a single response (confirmed live: top-level keys are
        just {"data": [...]}, no "meta"/pagination wrapper -- one row per
        team, ~13 rows for the whole league, so there's nothing to
        paginate)."""
        return self._http.get_json(STANDINGS_PATH, params={"season": season})

    def fetch_odds_page(
        self,
        day: date,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/odds -- one cursor-paginated page of bookmaker odds
        for every game on one date (verified live: `dates[]=YYYY-MM-DD` is
        required -- a bare request 400s with "At least one of dates or
        game_ids is required"). Only carries a rolling recent window (the
        current/upcoming season), not full historical archives -- see
        wnba_engine/balldontlie/odds_parser.py."""
        params: dict[str, object] = {"dates[]": day.isoformat(), "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(ODDS_PATH, params=params)

    def fetch_player_prop_odds_page(
        self,
        game_id: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/odds/player_props -- one cursor-paginated page of
        player-prop odds for one game (verified live: a single `game_id=
        <int>` is required, a DIFFERENT contract than fetch_odds_page's
        `dates[]=` -- a bare request or `dates[]=` 400s with "game_id must
        be an integer"). See
        wnba_engine/balldontlie/player_prop_odds_parser.py."""
        params: dict[str, object] = {"game_id": game_id, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(PLAYER_PROP_ODDS_PATH, params=params)

    def fetch_players_page(
        self,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/players -- one cursor-paginated page of EVERY player
        balldontlie has ever recorded (859 total, verified live), no
        season/date scoping -- same cursor contract as the other
        cursor-paginated endpoints (meta.next_cursor, absent on the final
        page)."""
        params: dict[str, object] = {"per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(PLAYERS_PATH, params=params)

    def fetch_player_stats_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/player_stats -- one cursor-paginated page of
        TRADITIONAL per-player-per-game box score stats (points, rebounds,
        assists, etc.), a different endpoint from
        fetch_player_advanced_stats_page's offensive/defensive rating and
        four factors. Same seasons[]/per_page/cursor contract as the other
        cursor-paginated endpoints (verified live)."""
        params: dict[str, object] = {"seasons[]": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(PLAYER_STATS_PATH, params=params)

    def fetch_team_stats_page(
        self,
        season: int,
        *,
        cursor: int | None = None,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> object:
        """GET /wnba/v1/team_stats -- one cursor-paginated page of
        TRADITIONAL per-team-per-game box score stats. Same
        seasons[]/per_page/cursor contract as fetch_player_stats_page
        (verified live)."""
        params: dict[str, object] = {"seasons[]": season, "per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        return self._http.get_json(TEAM_STATS_PATH, params=params)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BalldontlieClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
