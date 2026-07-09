"""ESPN HTTP client. Endpoint calls only — parsing lives in parser.py."""

from __future__ import annotations

from datetime import date

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "espn"


class EspnClient:
    def __init__(self, settings: Settings) -> None:
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.espn_base_url,
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
