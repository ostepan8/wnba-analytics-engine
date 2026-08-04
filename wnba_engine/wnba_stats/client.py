"""stats.wnba.com client.

Same host family as stats.nba.com and it inherits that API's two quirks:

- **It refuses requests that do not look like a browser.** Without a
  Referer/Origin pointing at wnba.com and the `x-nba-stats-*` headers, the
  endpoint hangs until timeout rather than returning an error, which is a
  much worse failure mode than a 403 and is why the headers are pinned here
  rather than left to a caller.
- **`LeagueID=10` is the WNBA.** 00 is the NBA and 20 the G-League. Omitting
  it returns NBA data with no indication that anything is wrong -- a silent
  wrong-sport answer, which is the reason it is passed explicitly on every
  call that accepts it.

No API key. Pacing is deliberately slower than this project's other
providers: it is an unauthenticated public endpoint with no published
quota, and a full historical sweep is thousands of requests.
"""

from __future__ import annotations

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "wnba_stats"
LEAGUE_ID = "10"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.wnba.com/",
    "Origin": "https://www.wnba.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


class WnbaStatsClient:
    def __init__(self, settings: Settings) -> None:
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.wnba_stats_base_url,
            timeout_seconds=max(settings.request_timeout_seconds, 30.0),
            min_request_interval_seconds=settings.wnba_stats_min_request_interval_seconds,
            headers=_BROWSER_HEADERS,
        )

    def fetch_game_log(self, season: int, *, season_type: str = "Regular Season") -> object:
        """GET /leaguegamelog -- two rows per game, one per team.

        `Season` is the START year as a bare integer for the WNBA (2025),
        unlike the NBA's "2024-25" span format. Passing a span silently
        returns nothing.
        """
        return self._http.get_json(
            "leaguegamelog",
            params={
                "Counter": 0,
                "Direction": "ASC",
                "LeagueID": LEAGUE_ID,
                "PlayerOrTeam": "T",
                "Season": season,
                "SeasonType": season_type,
                "Sorter": "DATE",
            },
        )

    def fetch_play_by_play(self, game_id: str) -> object:
        """GET /playbyplayv2 -- events with PLAYER1/2/3_ID attribution."""
        return self._http.get_json(
            "playbyplayv2",
            params={"GameID": game_id, "StartPeriod": 1, "EndPeriod": 14},
        )

    def fetch_shot_chart(self, game_id: str, season: int) -> object:
        """GET /shotchartdetail -- one row per attempt, with coordinates.

        Every filter has to be present even when empty; the endpoint 400s on
        a missing parameter rather than defaulting it. PlayerID=0 and
        TeamID=0 mean "all", which is what makes this one request per game
        rather than one per player.
        """
        return self._http.get_json(
            "shotchartdetail",
            params={
                "ContextMeasure": "FGA",
                "LeagueID": LEAGUE_ID,
                "Season": season,
                "SeasonType": "Regular Season",
                "GameID": game_id,
                "PlayerID": 0,
                "TeamID": 0,
                "Period": 0,
                "StartPeriod": 1,
                # 10, not 14. playbyplayv2 accepts either; shotchartdetail
                # 400s on anything above 10 with no message saying so.
                "EndPeriod": 10,
                "LastNGames": 0,
                "Month": 0,
                "OpponentTeamID": 0,
                "RangeType": 0,
                "StartRange": 0,
                "EndRange": 28800,
                "AheadBehind": "",
                "ClutchTime": "",
                "Conference": "",
                "DateFrom": "",
                "DateTo": "",
                "Division": "",
                "GameSegment": "",
                "PlayerPosition": "",
                "PointDiff": "",
                "Position": "",
                "RookieYear": "",
                "SeasonSegment": "",
                "VsConference": "",
                "VsDivision": "",
                "ContextFilter": "",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WnbaStatsClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
