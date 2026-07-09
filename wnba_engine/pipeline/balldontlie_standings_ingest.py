"""balldontlie standings ingestion: paid API (GOAT tier), current official
league standings at team-season granularity.

Unlike the per-game pipelines (advanced stats, plays, shot zones),
standings are season-level, not per-game -- there's no game dimension at
all, so this pipeline skips balldontlie_game_resolution's game crosswalk
phase entirely. Just one phase: fetch the season's standings (single
response, no pagination -- verified live) and resolve each row's team via
find_team_by_abbreviation, same as the team-advanced-stats pipeline uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

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


def backfill_season(
    db: Database, client: BalldontlieClient, season: int
) -> BdlStandingsIngestResult:
    payload = client.fetch_standings(season)
    rows = parse_standings(payload)
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
        conn.commit()
    return result
