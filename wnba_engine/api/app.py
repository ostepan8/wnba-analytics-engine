"""The read-only HTTP API over the engine's dataset.

Public by design (it is served at a public hostname through a Cloudflare
Tunnel) and therefore built to be safe when public:

  * **No writes.** Every route reads; the connection is marked read-only in
    deps.py so Postgres refuses one even if a future handler tries.
  * **No credentials reachable.** The provider API keys live only in the
    scheduler's environment. This process never loads them.
  * **Every query bounded.** Limits are validated here and capped again in
    analytics_repo -- the tables behind these endpoints are append-only price
    history in the hundreds of thousands of rows.
  * **Cacheable.** Each route sets Cache-Control so Cloudflare absorbs repeat
    traffic instead of forwarding it to a machine at home.

There is deliberately no authentication. The dataset is public WNBA data with
no personal information in it, and a key embedded in a public analytics page
protects nothing while making the page harder to share.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from wnba_engine.api.deps import lifespan
from wnba_engine.api.routes import games, health, markets, stats

TITLE = "WNBA Analytics Engine API"
DESCRIPTION = (
    "Read-only access to WNBA odds history, prediction-market prices, outcomes, "
    "box scores, and the cross-venue divergence log."
)

# Browsers calling this from a separately-hosted analytics page need CORS. The
# allowed origins are configurable and default to open, which is consistent with
# an unauthenticated public read API -- CORS is not an access control here, and
# pretending otherwise would only make it look like one.
DEFAULT_ALLOWED_ORIGINS = "*"


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(title=TITLE, description=DESCRIPTION, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    for module in (health, markets, games, stats):
        app.include_router(module.router)

    _mount_dashboard(app)
    return app


def _mount_dashboard(app: FastAPI) -> None:
    """Serve the analytics page from the same origin as the data it reads.

    Mounted LAST and at the root. Starlette matches explicit routes before
    mounts, so every API path above still wins; this only catches what is left.
    Same-origin means the page needs no CORS grant and no configured API base --
    it fetches relative paths and works identically over the tunnel, over the
    tailnet, and on localhost.
    """
    static_dir = Path(__file__).resolve().parent / "static"
    if not static_dir.is_dir():
        # The API is useful without the page; the page is useless without the
        # API. Missing static files degrade to a data-only service rather than
        # refusing to start.
        logging.getLogger(__name__).warning(
            "no static directory at %s; serving API only", static_dir
        )
        return
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")


def _allowed_origins() -> list[str]:
    raw = os.environ.get("WNBA_API_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("WNBA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


app = create_app()
