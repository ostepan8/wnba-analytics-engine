"""the-odds-api final-score ingestion: a second, independent source of
completed-game scores, captured purely as a data-quality CROSS-CHECK
against games.home_score/away_score -- never written back into that
column (see db/migrations/0021_odds_api_game_scores.sql and
wnba_engine/validation/consistency_checks.py's
check_odds_api_score_matches_game_score).

Current-state sweep only (mirrors snapshot-injuries/
snapshot-balldontlie-injuries' "current state" pattern): daysFrom bounds
how far back the endpoint looks for completed games each run, so a
recurring schedule with a trailing window naturally re-covers anything a
missed run would have caught.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import timedelta

from wnba_engine.db.pool import Database
from wnba_engine.odds_api.client import OddsApiClient
from wnba_engine.odds_api.scores_parser import parse_scores
from wnba_engine.repositories import entity_repo, odds_api_scores_repo

logger = logging.getLogger(__name__)

SOURCE = "the_odds_api"
DEFAULT_DAYS_FROM = 3
# Same reasoning as odds_api_ingest.GAME_MATCH_WINDOW -- the-odds-api gives
# an exact commence_time, so a tight window is safe.
GAME_MATCH_WINDOW = timedelta(hours=3)


@dataclass(frozen=True, slots=True)
class OddsApiScoresIngestResult:
    games_seen: int = 0
    rows_inserted: int = 0
    unresolved_games: int = 0


def snapshot_current_scores(
    db: Database, client: OddsApiClient, *, days_from: int = DEFAULT_DAYS_FROM
) -> OddsApiScoresIngestResult:
    payload = client.fetch_scores(days_from=days_from)
    rows = parse_scores(payload)
    result = OddsApiScoresIngestResult()
    with db.connection() as conn:
        for row in rows:
            result = replace(result, games_seen=result.games_seen + 1)
            game_id = entity_repo.lookup_internal_id(
                conn, SOURCE, entity_repo.ENTITY_GAME, row.external_id
            )
            if game_id is None:
                game_id = entity_repo.find_game_id_by_teams(
                    conn, row.home_team, row.away_team, row.commence_time, window=GAME_MATCH_WINDOW
                )
                if game_id is None:
                    logger.warning(
                        "unresolved the_odds_api score event external_id=%s (%s vs %s, "
                        "commence_time=%s) -- skipping",
                        row.external_id,
                        row.home_team,
                        row.away_team,
                        row.commence_time,
                    )
                    result = replace(result, unresolved_games=result.unresolved_games + 1)
                    continue
                entity_repo.record_crosswalk_mapping(
                    conn, SOURCE, entity_repo.ENTITY_GAME, row.external_id, game_id
                )
            inserted = odds_api_scores_repo.insert_score(conn, game_id=game_id, row=row)
            if inserted:
                result = replace(result, rows_inserted=result.rows_inserted + 1)
        conn.commit()
    return result
