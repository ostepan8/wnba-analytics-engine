"""Environment-backed settings. Fails fast if required config is missing."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # no-op if .env doesn't exist; never overrides a real env var

DEFAULT_DATABASE_URL = "postgresql://wnba:wnba@localhost:5434/wnba_engine"
DEFAULT_ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
# ESPN's site API is uniform across every sport it covers -- confirmed live
# 2026-08-22, identical response shape to the WNBA scoreboard endpoint.
DEFAULT_ESPN_NBA_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
DEFAULT_KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_POLYMARKET_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
# A SECOND Polymarket host, and the distinction matters. Gamma serves market
# metadata and a current quote; data-api serves the on-chain fill history.
# Only the latter survives -- clob.polymarket.com/prices-history is a rolling
# ~30-day cache (verified 2026-08-03: a June market with $377k volume returns
# zero points), while data-api returns every fill back to 2024-09-20 for WNBA.
DEFAULT_POLYMARKET_DATA_BASE_URL = "https://data-api.polymarket.com"
DEFAULT_WAYBACK_BASE_URL = "https://web.archive.org"
DEFAULT_WNBA_STATS_BASE_URL = "https://stats.wnba.com/stats"
# Same platform, different host and LeagueID (00 vs 10) -- see
# wnba_engine/wnba_stats/client.py's league handling. Live-verification of
# this exact host was blocked by this sandbox's network (stats.wnba.com
# failed identically as a control), so treat this as high-confidence by
# documented pattern (this repo's own client already documents
# "00 is the NBA"), not independently confirmed live.
DEFAULT_NBA_STATS_BASE_URL = "https://stats.nba.com/stats"
# Unauthenticated public endpoint with no published quota, and a full
# historical sweep is thousands of requests. Slower than every other
# provider here on purpose. Shared by the NBA client too -- no reason for
# different courtesy pacing on the same underlying platform.
DEFAULT_WNBA_STATS_MIN_REQUEST_INTERVAL_SECONDS = 0.6
DEFAULT_BALLDONTLIE_BASE_URL = "https://api.balldontlie.io"
DEFAULT_ODDS_API_BASE_URL = "https://api.the-odds-api.com"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.5
# Archive.org is a free, donation-funded public service, not a commercial
# API -- deliberately slower than our other providers' default out of
# courtesy for a long (~1000+ request) backfill run.
DEFAULT_WAYBACK_MIN_REQUEST_INTERVAL_SECONDS = 1.5
# GOAT tier is documented at 600 req/min (100ms/request); staying under that
# with margin rather than pushing the exact limit.
DEFAULT_BALLDONTLIE_MIN_REQUEST_INTERVAL_SECONDS = 0.15
# the-odds-api has no documented hard rate limit for this plan tier
# (quota is request-count-based, not requests/sec) -- this is courtesy
# pacing, matching the conservatism of the other paid-API defaults above.
DEFAULT_ODDS_API_MIN_REQUEST_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    espn_base_url: str
    espn_nba_base_url: str
    kalshi_base_url: str
    polymarket_gamma_base_url: str
    polymarket_data_base_url: str
    wayback_base_url: str
    wnba_stats_base_url: str
    nba_stats_base_url: str
    wnba_stats_min_request_interval_seconds: float
    balldontlie_base_url: str
    odds_api_base_url: str
    request_timeout_seconds: float
    min_request_interval_seconds: float
    wayback_min_request_interval_seconds: float
    balldontlie_min_request_interval_seconds: float
    odds_api_min_request_interval_seconds: float
    # Kalshi market data is readable without auth today; if that changes, set
    # WNBA_ENGINE_KALSHI_API_KEY and the client will send it as a bearer token.
    kalshi_api_key: str | None
    # Required for any balldontlie call -- it's a paid API, no anonymous tier.
    balldontlie_api_key: str | None
    # Required for any the-odds-api call -- sent as a query param (`apiKey=`),
    # not a header (see wnba_engine/odds_api/client.py + http_client.py's
    # redact_query_param_keys for why that matters for logging).
    odds_api_key: str | None
    # Local inference (nephos). Optional everywhere: with no base url configured
    # the LLM name-resolution fallback simply does not run, and every caller
    # behaves exactly as it did before -- an unmatched name is dropped.
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("WNBA_ENGINE_DATABASE_URL", DEFAULT_DATABASE_URL),
        espn_base_url=os.environ.get("WNBA_ENGINE_ESPN_BASE_URL", DEFAULT_ESPN_BASE_URL),
        espn_nba_base_url=os.environ.get(
            "WNBA_ENGINE_ESPN_NBA_BASE_URL", DEFAULT_ESPN_NBA_BASE_URL
        ),
        kalshi_base_url=os.environ.get("WNBA_ENGINE_KALSHI_BASE_URL", DEFAULT_KALSHI_BASE_URL),
        polymarket_gamma_base_url=os.environ.get(
            "WNBA_ENGINE_POLYMARKET_GAMMA_BASE_URL", DEFAULT_POLYMARKET_GAMMA_BASE_URL
        ),
        polymarket_data_base_url=os.environ.get(
            "WNBA_ENGINE_POLYMARKET_DATA_BASE_URL", DEFAULT_POLYMARKET_DATA_BASE_URL
        ),
        wayback_base_url=os.environ.get("WNBA_ENGINE_WAYBACK_BASE_URL", DEFAULT_WAYBACK_BASE_URL),
        wnba_stats_base_url=os.environ.get(
            "WNBA_ENGINE_WNBA_STATS_BASE_URL", DEFAULT_WNBA_STATS_BASE_URL
        ),
        nba_stats_base_url=os.environ.get(
            "WNBA_ENGINE_NBA_STATS_BASE_URL", DEFAULT_NBA_STATS_BASE_URL
        ),
        wnba_stats_min_request_interval_seconds=float(
            os.environ.get(
                "WNBA_ENGINE_WNBA_STATS_MIN_REQUEST_INTERVAL_SECONDS",
                DEFAULT_WNBA_STATS_MIN_REQUEST_INTERVAL_SECONDS,
            )
        ),
        balldontlie_base_url=os.environ.get(
            "WNBA_ENGINE_BALLDONTLIE_BASE_URL", DEFAULT_BALLDONTLIE_BASE_URL
        ),
        odds_api_base_url=os.environ.get(
            "WNBA_ENGINE_ODDS_API_BASE_URL", DEFAULT_ODDS_API_BASE_URL
        ),
        request_timeout_seconds=float(
            os.environ.get("WNBA_ENGINE_REQUEST_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS)
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
        odds_api_min_request_interval_seconds=float(
            os.environ.get(
                "WNBA_ENGINE_ODDS_API_MIN_REQUEST_INTERVAL_SECONDS",
                DEFAULT_ODDS_API_MIN_REQUEST_INTERVAL_SECONDS,
            )
        ),
        kalshi_api_key=os.environ.get("WNBA_ENGINE_KALSHI_API_KEY") or None,
        balldontlie_api_key=os.environ.get("WNBA_ENGINE_BALLDONTLIE_API_KEY") or None,
        odds_api_key=os.environ.get("WNBA_ENGINE_ODDS_API_KEY") or None,
        llm_base_url=os.environ.get("WNBA_ENGINE_LLM_BASE_URL") or None,
        llm_api_key=os.environ.get("WNBA_ENGINE_LLM_API_KEY") or None,
        llm_model=os.environ.get("WNBA_ENGINE_LLM_MODEL", "fast"),
    )
