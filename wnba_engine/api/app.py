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
from starlette.exceptions import HTTPException

from wnba_engine.api.deps import lifespan
from wnba_engine.api.routes import (
    directory,
    games,
    health,
    lines,
    markets,
    shooting,
    slate,
    stats,
    trends,
)

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

# Single prefix for every data endpoint; see create_app for why it is mandatory.
API_PREFIX = "/api"


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

    # Everything lives under /api, and it has to.
    #
    # The client owns routing, so /players/36 is a page. It was also an
    # endpoint, and FastAPI matches routes before mounts -- so navigating to a
    # player returned raw JSON instead of the app. Two namespaces sharing one
    # URL space cannot both win; giving the API its own prefix settles it
    # permanently rather than per-collision.
    for module in (health, markets, directory, games, stats, shooting, lines, trends, slate):
        app.include_router(module.router, prefix=API_PREFIX)

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
    app.mount("/", _SinglePageApp(directory=static_dir, html=True), name="app")


class _SinglePageApp(StaticFiles):
    """StaticFiles that falls back to index.html for unknown paths.

    The client owns routing, so /players/36 is a real page but not a real file.
    Plain StaticFiles 404s it, which breaks every deep link, refresh and shared
    URL -- the app works only if you always arrive at "/" and click.

    Only a missing FILE falls through. A missing /assets/* bundle must stay a
    404: answering it with HTML makes a bad deploy look like a working one that
    renders nothing, which is far harder to diagnose.
    """

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # Starlette RAISES on a missing file rather than returning a 404
            # response, so checking the status code alone never fires.
            if exc.status_code != 404 or path.startswith("assets/"):
                raise
            return await super().get_response("index.html", scope)

        if response.status_code == 404 and not path.startswith("assets/"):
            return await super().get_response("index.html", scope)
        return response


def _allowed_origins() -> list[str]:
    raw = os.environ.get("WNBA_API_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("WNBA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


app = create_app()
