"""Kalshi HTTP client. Read-only market data — no trading endpoints, ever.

No API key is required for public market data today. If Kalshi starts
requiring one, set WNBA_ENGINE_KALSHI_API_KEY and it is sent as a bearer
token.
"""

from __future__ import annotations

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "kalshi"
SPORTS_CATEGORY = "Sports"
MARKETS_PAGE_LIMIT = 200


class KalshiClient:
    def __init__(self, settings: Settings) -> None:
        headers = (
            {"Authorization": f"Bearer {settings.kalshi_api_key}"}
            if settings.kalshi_api_key
            else None
        )
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.kalshi_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.min_request_interval_seconds,
            headers=headers,
        )

    def fetch_sports_series(self) -> object:
        """GET /series?category=Sports — all sports series (market families)."""
        return self._http.get_json("series", params={"category": SPORTS_CATEGORY})

    def fetch_markets_page(
        self,
        series_ticker: str,
        *,
        status: str = "open",
        cursor: str | None = None,
        limit: int = MARKETS_PAGE_LIMIT,
    ) -> object:
        """GET /markets?series_ticker=... — one cursor-paginated page."""
        params: dict[str, object] = {
            "series_ticker": series_ticker,
            "status": status,
            "limit": limit,
        }
        if cursor:
            params["cursor"] = cursor
        return self._http.get_json("markets", params=params)

    def fetch_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        *,
        start_ts: int,
        end_ts: int,
        period_interval: int,
    ) -> object:
        """GET /series/{s}/markets/{t}/candlesticks -- OHLC bars.

        Unlike the snapshot endpoints this is genuinely HISTORICAL: bars go
        back to market creation, not to some rolling window (verified
        2026-08-03 -- a season future opened 2026-05-22 still returns its
        first bar when queried with a 180-day lookback).

        THE WINDOW IS CAPPED AND THE CAP DEPENDS ON `period_interval`.
        Measured against the live API on the same date: 60-minute bars
        accept ~180 days per request and 400 was rejected with HTTP 400;
        1-minute bars accept ~3 days and 7 was rejected. The error is a bare
        400 with no explanation, so a caller that guesses too wide sees what
        looks like a broken endpoint. `backfill_candlesticks` chunks against
        `MAX_WINDOW_DAYS` for exactly this reason.
        """
        return self._http.get_json(
            f"series/{series_ticker}/markets/{market_ticker}/candlesticks",
            params={
                "start_ts": start_ts,
                "end_ts": end_ts,
                "period_interval": period_interval,
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KalshiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
