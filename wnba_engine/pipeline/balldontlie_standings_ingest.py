"""balldontlie standings ingestion: paid API (GOAT tier), current official
league standings at team-season granularity.

Unlike the per-game pipelines (advanced stats, plays, shot zones),
standings are season-level, not per-game -- there's no game dimension at
all, so this pipeline skips balldontlie_game_resolution's game crosswalk
phase entirely. Just one phase: fetch the season's standings (single
response, no pagination -- verified live) and resolve each row's team via
find_team_by_abbreviation, same as the team-advanced-stats pipeline uses.

Each resolved row is written to BOTH team_standings (current-state upsert)
AND team_standings_history (append-only snapshot) in the same transaction
-- see standings_repo module docstring and db/migrations/0015_standings_history.sql
for the dual-write rationale. One captured_at timestamp is shared across
every row in a single run (same pattern as injury_ingest/kalshi_ingest/
polymarket_ingest), so all teams in one backfill snapshot the same instant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.standings_parser import parse_standings
from wnba_engine.db.pool import Database
from wnba_engine.repositories import entity_repo, standings_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"


@dataclass(frozen=True, slots=True)
class BdlStandingsIngestResult:
    rows_seen: int = 0
    rows_inserted: int = 0
    unresolved_teams: int = 0
    history_rows_inserted: int = 0
    history_rows_skipped_no_change: int = 0


def backfill_season(
    db: Database, client: BalldontlieClient, season: int
) -> BdlStandingsIngestResult:
    payload = client.fetch_standings(season)
    rows = parse_standings(payload)
    captured_at = datetime.now(UTC)
    result = BdlStandingsIngestResult()
    with db.connection() as conn:
        for row in rows:
            result = replace(result, rows_seen=result.rows_seen + 1)
            team_id = entity_repo.find_team_by_abbreviation(conn, row.team.abbreviation)
            if team_id is None:
                logger.warning(
                    "unresolved team abbreviation=%s for balldontlie standings -- skipping",
                    row.team.abbreviation,
                )
                result = replace(result, unresolved_teams=result.unresolved_teams + 1)
                continue
            standings_repo.upsert_standings(
                conn, team_id=team_id, season=row.season, source=SOURCE, row=row
            )
            result = replace(result, rows_inserted=result.rows_inserted + 1)
            inserted = standings_repo.insert_standings_history(
                conn,
                team_id=team_id,
                season=row.season,
                source=SOURCE,
                row=row,
                captured_at=captured_at,
            )
            if inserted:
                result = replace(result, history_rows_inserted=result.history_rows_inserted + 1)
            else:
                result = replace(
                    result,
                    history_rows_skipped_no_change=result.history_rows_skipped_no_change + 1,
                )
        conn.commit()
    return result
