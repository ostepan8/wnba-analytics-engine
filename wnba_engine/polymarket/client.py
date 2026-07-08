"""Polymarket Gamma API client. Read-only market data — no trading, ever."""

from __future__ import annotations

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "polymarket"
WNBA_TAG_SLUG = "wnba"
EVENTS_PAGE_LIMIT = 100


class PolymarketClient:
    def __init__(self, settings: Settings) -> None:
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.polymarket_gamma_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.min_request_interval_seconds,
        )

    def fetch_wnba_events_page(
        self,
        *,
        closed: bool = False,
        limit: int = EVENTS_PAGE_LIMIT,
        offset: int = 0,
    ) -> object:
        """GET /events?tag_slug=wnba — one offset-paginated page.

        Note: `tag_slug` is the parameter that actually filters; a bare
        `tag=wnba` does not (verified live).
        """
        return self._http.get_json(
            "events",
            params={
                "tag_slug": WNBA_TAG_SLUG,
                "closed": str(closed).lower(),
                "limit": limit,
                "offset": offset,
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PolymarketClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
