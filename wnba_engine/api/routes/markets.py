"""The cross-venue divergence log, and a dataset overview.

MODELING_FINDINGS.md establishes that prediction markets lead the sportsbook
and cannot establish whether that lead is tradeable -- the gap is temporal, not
statistical. The forward log is the instrument built to close it, so these
endpoints exist to read an experiment in progress, not to report a result.

That is why every rate below is served with its denominator. CLV needs roughly
120 graded observations to say anything and ROI needs ~10,600; a survival rate
shown without its count invites precisely the over-reading the underlying
research is careful to avoid.

Read-only, like everything else here. There is no order placement anywhere in
this codebase and none should be added (ROADMAP.md non-goals).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from psycopg import Connection

from wnba_engine.api.deps import get_connection
from wnba_engine.repositories import analytics_repo

router = APIRouter(tags=["markets"])

DIVERGENCE_MAX_AGE = 60
SUMMARY_MAX_AGE = 300


@router.get("/summary")
def dataset_summary(
    response: Response, conn: Connection = Depends(get_connection)
) -> dict[str, object]:
    """What is in the database, and how current it is."""
    response.headers["Cache-Control"] = f"public, max-age={SUMMARY_MAX_AGE}"
    return analytics_repo.fetch_summary(conn)


@router.get("/divergences")
def list_divergences(
    response: Response,
    venue: str | None = Query(None, pattern="^(polymarket|kalshi)$"),
    graded_only: bool = Query(False, description="Only observations that have been graded."),
    limit: int = Query(100, ge=1, le=500),
    conn: Connection = Depends(get_connection),
) -> dict[str, object]:
    """Individual divergence observations, newest first."""
    response.headers["Cache-Control"] = f"public, max-age={DIVERGENCE_MAX_AGE}"
    rows = analytics_repo.fetch_divergences(
        conn, venue=venue, graded_only=graded_only, limit=limit
    )
    return {"divergences": rows, "count": len(rows)}


@router.get("/divergences/summary")
def divergence_summary(
    response: Response, conn: Connection = Depends(get_connection)
) -> dict[str, object]:
    """Per-venue aggregates, each rate reported alongside the count it came from."""
    response.headers["Cache-Control"] = f"public, max-age={SUMMARY_MAX_AGE}"
    return {"venues": analytics_repo.fetch_divergence_summary(conn)}
