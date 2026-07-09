"""balldontlie /wnba/v1/players sweep: paid API (GOAT tier). A global
backfill, NOT season-scoped -- the endpoint returns every player
balldontlie has ever recorded regardless of recent game activity
(verified live: no season/date filter accepted or required).

Bio data (height/weight/jersey_number/college/age) already gets populated
as a side effect of players appearing in the advanced-stats/shot-zone
pipelines (see resolve_or_create_player_by_name), but those only ever see
players who appeared in a recent-season game. This sweep reaches players
neither of those pipelines ever touch -- inactive/historical players and
ESPN-only identities balldontlie still has bio data for. It's also the
first balldontlie pipeline that can originate a brand-new canonical player
identity (via resolve_or_create_player_by_name's create path) rather than
only ever matching an existing one by name, since there's no ESPN box
score guaranteed to have created the player first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.players_parser import parse_players
from wnba_engine.db.pool import Database
from wnba_engine.repositories import entity_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"
MAX_PAGES = 200  # safety valve against a runaway cursor loop
PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class BdlPlayersIngestResult:
    pages_fetched: int = 0
    players_seen: int = 0
    players_processed: int = 0


def backfill_players(db: Database, client: BalldontlieClient) -> BdlPlayersIngestResult:
    """Sweep every page of /wnba/v1/players, resolving each row through
    the same name-based crosswalk the advanced-stats/shot-zone pipelines
    use. `players_processed` doesn't distinguish created vs. updated --
    resolve_or_create_player_by_name's return value (an internal id) makes
    no such distinction either, and a coarser count is sufficient here
    since the live-verification step compares before/after bio-null
    counts directly against the database."""
    result = BdlPlayersIngestResult()
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        payload = client.fetch_players_page(cursor=cursor, per_page=PAGE_SIZE)
        rows = parse_players(payload)
        result = replace(result, pages_fetched=result.pages_fetched + 1)
        with db.connection() as conn:
            for row in rows:
                result = replace(result, players_seen=result.players_seen + 1)
                entity_repo.resolve_or_create_player_by_name(
                    conn,
                    SOURCE,
                    row.external_id,
                    row.full_name,
                    row.position,
                    row.height,
                    row.weight,
                    row.jersey_number,
                    row.college,
                    row.age,
                )
                result = replace(result, players_processed=result.players_processed + 1)
            conn.commit()
        if len(rows) < PAGE_SIZE:
            return result
        cursor = _next_cursor(payload)
        if cursor is None:
            return result
    logger.warning("balldontlie players sweep exceeded %d pages", MAX_PAGES)
    return result


def _next_cursor(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, int) else None
