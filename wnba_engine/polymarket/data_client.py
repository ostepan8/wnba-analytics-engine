"""Polymarket data-api client. Read-only fill history -- no trading, ever.

Separate from `PolymarketClient` because it is a different HOST with
different semantics, not another route on Gamma:

  gamma-api.polymarket.com  market metadata + a current quote (mutable state)
  data-api.polymarket.com   on-chain fill history (immutable facts)

The split matters operationally too. Gamma is what the 30-minute capture host
polls and what goes stale if that host dies; data-api is recoverable at any
later date, so it belongs in a backfill rather than in the capture loop.
"""

from __future__ import annotations

from wnba_engine.config import Settings
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "polymarket"
#: Server-side maximum observed on /trades. Larger values are silently
#: clamped rather than rejected, which would make a backfill look complete
#: while skipping records, so this is pinned rather than pushed.
TRADES_PAGE_LIMIT = 500


class PolymarketDataClient:
    def __init__(self, settings: Settings) -> None:
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.polymarket_data_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.min_request_interval_seconds,
            # data-api 403s a request with no User-Agent (verified 2026-08-03
            # -- the same call succeeds the moment one is set). Gamma does
            # not, which is why PolymarketClient gets away without it.
            headers={"User-Agent": "wnba-analytics-engine (+https://github.com/ostepan8)"},
        )

    def fetch_trades_page(
        self, condition_id: str, *, limit: int = TRADES_PAGE_LIMIT, offset: int = 0
    ) -> object:
        """GET /trades?market={conditionId} -- one offset-paginated page.

        `market` takes the CONDITION id (0x...), not a clobTokenId. Passing a
        token id returns an empty list rather than an error, so a mixup looks
        exactly like a market that never traded.
        """
        return self._http.get_json(
            "trades", params={"market": condition_id, "limit": limit, "offset": offset}
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PolymarketDataClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
