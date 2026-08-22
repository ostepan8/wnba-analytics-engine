"""ESPN HTTP client. Endpoint calls only — parsing lives in parser.py.

ESPN's site API is uniform across every sport it covers -- confirmed live
2026-08-22 for the NBA (identical response shape to the WNBA scoreboard
endpoint).

PROVIDER STRINGS ARE LEAGUE-SCOPED ("espn" / "espn_nba"), NOT SHARED --
this was verified wrong once already. Confirmed live 2026-08-22: WNBA's
Minnesota Lynx and NBA's Detroit Pistons both carry ESPN team id "8".
ESPN's ids are small per-sport integers, not a single global space, so a
shared "espn" provider string caused a real cross-league identity
collision in this project's provider_entity_map during this expansion's
own testing -- an NBA team's crosswalk row matched an existing WNBA team's
row and overwrote its name. Never reuse one provider string for both
leagues here; see wnba_stats/client.py's wnba_stats/nba_stats split for
the same fix applied earlier by inference (this one was caught by testing,
not foreseen).
"""

from __future__ import annotations

from datetime import date

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

# Not a Literal: callers pass this through from CLI options (click.Choice
# yields plain str) and config, so the type stays str at this boundary.
League = str

_PROVIDERS = {"wnba": "espn", "nba": "espn_nba"}


class EspnClient:
    def __init__(self, settings: Settings, *, league: League = "wnba") -> None:
        if league not in _PROVIDERS:
            raise ValueError(f"unsupported league: {league!r}")
        self.league = league
        self.provider = _PROVIDERS[league]
        base_url = settings.espn_base_url if league == "wnba" else settings.espn_nba_base_url
        self._http = JsonHttpClient(
            provider=self.provider,
            base_url=base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.min_request_interval_seconds,
        )

    def fetch_scoreboard(self, day: date) -> object:
        """GET /scoreboard?dates=YYYYMMDD — all games on one date."""
        return self._http.get_json("scoreboard", params={"dates": day.strftime("%Y%m%d")})

    def fetch_summary(self, event_id: str) -> object:
        """GET /summary?event=<espn_event_id> — box score for one game."""
        return self._http.get_json("summary", params={"event": event_id})

    def fetch_injuries(self) -> object:
        """GET /injuries — current league-wide injury report, all teams.

        Current-state only: this reflects today's report regardless of any
        date context, there is no historical version of this endpoint.
        """
        return self._http.get_json("injuries")

    def fetch_transactions(self, season: int, page: int = 1, limit: int = 200) -> object:
        """GET /transactions?season=<year>&limit=<limit>&page=<page> — roster
        moves (signings, waivers, releases, trades, front-office/coaching
        hires, ...) for one season.

        `limit=200` covers most seasons in a single page (confirmed live:
        2022-2024 each returned `pageCount: 1`), but a busy trade-deadline
        season can exceed it -- 2025 returned `count: 220` across
        `pageCount: 2`. Callers must check the response's `pageCount` and
        loop `page` (page-number pagination, 1-indexed) rather than assuming
        one page is always enough. The response's echoed `season.year`
        field is NOT reliable -- it always reflects the *current* season
        regardless of what was requested; trust each transaction's own
        `date` field instead (see espn/transactions_parser.py).
        """
        return self._http.get_json(
            "transactions", params={"season": season, "limit": limit, "page": page}
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EspnClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
