"""balldontlie play-by-play ingestion: paid API (GOAT tier). One request
per game (fetch_plays returns the whole game in one response -- confirmed
live, no cursor pagination on this endpoint). Games are resolved via the
shared balldontlie_game_resolution module, the same crosswalk
advanced-stats ingestion uses, so a season already backfilled for advanced
stats doesn't re-match games here.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from psycopg import Connection

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.balldontlie.plays_parser import parse_plays
from wnba_engine.db.pool import Database
from wnba_engine.models.plays import BdlPlay
from wnba_engine.pipeline.balldontlie_game_resolution import resolve_games_for_season
from wnba_engine.repositories import entity_repo, plays_repo

logger = logging.getLogger(__name__)

SOURCE = "balldontlie"


@dataclass(frozen=True, slots=True)
class BdlPlaysIngestResult:
    games_seen: int = 0
    games_resolved: int = 0
    games_unresolved: int = 0
    plays_seen: int = 0
    plays_inserted: int = 0
    games_with_unresolved_teams: int = 0


def backfill_season_plays(
    db: Database, client: BalldontlieClient, season: int
) -> BdlPlaysIngestResult:
    game_resolution = resolve_games_for_season(db, client, season)
    result = BdlPlaysIngestResult(
        games_seen=game_resolution.games_seen,
        games_resolved=game_resolution.games_resolved,
        games_unresolved=game_resolution.games_unresolved,
    )
    for external_id, canonical_game_id in game_resolution.resolved:
        payload = client.fetch_plays(int(external_id))
        plays = parse_plays(payload)
        with db.connection() as conn:
            team_id_by_external_id = _resolve_teams(conn, plays)
            inserted = plays_repo.insert_plays(
                conn,
                game_id=canonical_game_id,
                source=SOURCE,
                plays=plays,
                team_id_by_external_id=team_id_by_external_id,
            )
            conn.commit()
        result = replace(
            result,
            plays_seen=result.plays_seen + len(plays),
            plays_inserted=result.plays_inserted + inserted,
        )
        if _has_unresolved_team(plays, team_id_by_external_id):
            result = replace(
                result, games_with_unresolved_teams=result.games_with_unresolved_teams + 1
            )
    return result


def _resolve_teams(conn: Connection, plays: Sequence[BdlPlay]) -> dict[str, int]:
    team_id_by_external_id: dict[str, int] = {}
    for play in plays:
        if play.team is None or play.team.external_id in team_id_by_external_id:
            continue
        team_id = entity_repo.find_team_by_abbreviation(conn, play.team.abbreviation)
        if team_id is not None:
            team_id_by_external_id[play.team.external_id] = team_id
        else:
            logger.warning(
                "unresolved team abbreviation=%s for balldontlie play-by-play -- "
                "affected plays will have NULL team_id",
                play.team.abbreviation,
            )
    return team_id_by_external_id


def _has_unresolved_team(plays: Sequence[BdlPlay], team_id_by_external_id: dict[str, int]) -> bool:
    return any(
        play.team is not None and play.team.external_id not in team_id_by_external_id
        for play in plays
    )
