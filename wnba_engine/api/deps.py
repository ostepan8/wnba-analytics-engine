"""Database wiring for the API.

One pool for the process, opened at startup and closed at shutdown, handed to
routes as a request-scoped connection. FastAPI's dependency system returns the
connection to the pool even when a handler raises, which is the only reliable
way to avoid leaking one per failed request.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from psycopg import Connection

from wnba_engine.config import load_settings
from wnba_engine.db.pool import Database

logger = logging.getLogger(__name__)

# Sized for a read API in front of a single Postgres, not for throughput. Every
# handler holds a connection for one short query, so this is a queue depth, not
# a concurrency target -- and Postgres pays for idle connections.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 8


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    database = Database(
        load_settings().database_url, min_size=POOL_MIN_SIZE, max_size=POOL_MAX_SIZE
    )
    app.state.database = database
    try:
        yield
    finally:
        database.close()


def get_connection(request: Request) -> Iterator[Connection]:
    """Request-scoped read connection."""
    database: Database = request.app.state.database
    with database.connection() as conn:
        _mark_read_only(conn)
        yield conn


def _mark_read_only(conn: Connection) -> None:
    """Declare the session read-only, not merely conventionally so.

    The API has no write path, and a stray UPDATE in a future handler should be
    refused by Postgres rather than quietly mutate the dataset the scheduler is
    filling. psycopg refuses this while a transaction is open; a pooled
    connection is handed over idle, so that should not happen -- but a failure
    to *harden* must not take the read path down with it.
    """
    try:
        conn.read_only = True
    except Exception:  # noqa: BLE001 -- defence in depth, not a correctness requirement
        logger.warning("could not set the session read-only; continuing", exc_info=True)
