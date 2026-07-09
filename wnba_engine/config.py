"""Environment-backed settings. Fails fast if required config is missing."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # no-op if .env doesn't exist; never overrides a real env var

DEFAULT_DATABASE_URL = "postgresql://wnba:wnba@localhost:5434/wnba_engine"
DEFAULT_ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
DEFAULT_KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_POLYMARKET_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
DEFAULT_WAYBACK_BASE_URL = "https://web.archive.org"
DEFAULT_BALLDONTLIE_BASE_URL = "https://api.balldontlie.io"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.5
# Archive.org is a free, donation-funded public service, not a commercial
# API -- deliberately slower than our other providers' default out of
# courtesy for a long (~1000+ request) backfill run.
DEFAULT_WAYBACK_MIN_REQUEST_INTERVAL_SECONDS = 1.5
# GOAT tier is documented at 600 req/min (100ms/request); staying under that
# with margin rather than pushing the exact limit.
DEFAULT_BALLDONTLIE_MIN_REQUEST_INTERVAL_SECONDS = 0.15


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    espn_base_url: str
    kalshi_base_url: str
    polymarket_gamma_base_url: str
    wayback_base_url: str
    balldontlie_base_url: str
    request_timeout_seconds: float
    min_request_interval_seconds: float
    wayback_min_request_interval_seconds: float
    balldontlie_min_request_interval_seconds: float
    # Kalshi market data is readable without auth today; if that changes, set
    # WNBA_ENGINE_KALSHI_API_KEY and the client will send it as a bearer token.
    kalshi_api_key: str | None
    # Required for any balldontlie call -- it's a paid API, no anonymous tier.
    balldontlie_api_key: str | None


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("WNBA_ENGINE_DATABASE_URL", DEFAULT_DATABASE_URL),
        espn_base_url=os.environ.get("WNBA_ENGINE_ESPN_BASE_URL", DEFAULT_ESPN_BASE_URL),
        kalshi_base_url=os.environ.get("WNBA_ENGINE_KALSHI_BASE_URL", DEFAULT_KALSHI_BASE_URL),
        polymarket_gamma_base_url=os.environ.get(
            "WNBA_ENGINE_POLYMARKET_GAMMA_BASE_URL", DEFAULT_POLYMARKET_GAMMA_BASE_URL
        ),
        wayback_base_url=os.environ.get("WNBA_ENGINE_WAYBACK_BASE_URL", DEFAULT_WAYBACK_BASE_URL),
        balldontlie_base_url=os.environ.get(
            "WNBA_ENGINE_BALLDONTLIE_BASE_URL", DEFAULT_BALLDONTLIE_BASE_URL
        ),
        request_timeout_seconds=float(
            os.environ.get(
                "WNBA_ENGINE_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS
            )
        ),
        min_request_interval_seconds=float(
            os.environ.get(
                "WNBA_ENGINE_MIN_REQUEST_INTERVAL_SECONDS",
                DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
            )
        ),
        wayback_min_request_interval_seconds=float(
            os.environ.get(
                "WNBA_ENGINE_WAYBACK_MIN_REQUEST_INTERVAL_SECONDS",
                DEFAULT_WAYBACK_MIN_REQUEST_INTERVAL_SECONDS,
            )
        ),
        balldontlie_min_request_interval_seconds=float(
            os.environ.get(
                "WNBA_ENGINE_BALLDONTLIE_MIN_REQUEST_INTERVAL_SECONDS",
                DEFAULT_BALLDONTLIE_MIN_REQUEST_INTERVAL_SECONDS,
            )
        ),
        kalshi_api_key=os.environ.get("WNBA_ENGINE_KALSHI_API_KEY") or None,
        balldontlie_api_key=os.environ.get("WNBA_ENGINE_BALLDONTLIE_API_KEY") or None,
    )
