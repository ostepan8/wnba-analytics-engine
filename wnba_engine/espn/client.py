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

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EspnClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
