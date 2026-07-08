"""ESPN ingestion: scoreboard + box scores -> canonical tables.

sync_date(day) ingests one date; backfill(since, until) sweeps a range.
Failures on a single game are logged with context and counted, then the
run continues — one bad payload must not abort a multi-season backfill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, timedelta

from wnba_engine.db.pool import Database
from wnba_engine.errors import WnbaEngineError
from wnba_engine.espn.client import EspnClient
from wnba_engine.espn.parser import parse_scoreboard, parse_summary
from wnba_engine.models.games import ScoreboardGame
from wnba_engine.repositories import entity_repo, stats_repo

logger = logging.getLogger(__name__)

SOURCE = "espn"


@dataclass(frozen=True, slots=True)
class EspnIngestResult:
    games_seen: int = 0
    games_upserted: int = 0
    box_scores_ingested: int = 0
    failures: int = 0

    def merged_with(self, other: EspnIngestResult) -> EspnIngestResult:
        return EspnIngestResult(
            games_seen=self.games_seen + other.games_seen,
            games_upserted=self.games_upserted + other.games_upserted,
            box_scores_ingested=self.box_scores_ingested + other.box_scores_ingested,
            failures=self.failures + other.failures,
        )


def sync_date(db: Database, client: EspnClient, day: date) -> EspnIngestResult:
    """Ingest all games (and box scores for finished games) for one date."""
    games = parse_scoreboard(client.fetch_scoreboard(day))
    result = EspnIngestResult(games_seen=len(games))
    for game in games:
        try:
            ingested_box = _ingest_game(db, client, game)
        except WnbaEngineError:
            logger.exception(
                "failed to ingest game provider=espn external_id=%s date=%s",
                game.external_id,
                day.isoformat(),
            )
            result = replace(result, failures=result.failures + 1)
            continue
        result = replace(
            result,
            games_upserted=result.games_upserted + 1,
            box_scores_ingested=result.box_scores_ingested + (1 if ingested_box else 0),
        )
    return result


def backfill(db: Database, client: EspnClient, since: date, until: date) -> EspnIngestResult:
    """Ingest every date in [since, until], inclusive."""
    if since > until:
        raise ValueError(f"since ({since}) must not be after until ({until})")
    result = EspnIngestResult()
    day = since
    while day <= until:
        try:
            result = result.merged_with(sync_date(db, client, day))
        except WnbaEngineError:
            # A whole-date failure (scoreboard fetch/parse) is one failure unit.
            logger.exception("failed to ingest scoreboard date=%s", day.isoformat())
            result = replace(result, failures=result.failures + 1)
        day += timedelta(days=1)
    return result


def _ingest_game(db: Database, client: EspnClient, game: ScoreboardGame) -> bool:
    """Upsert one game (+ box score when final). Returns True if box ingested."""
    summary = parse_summary(client.fetch_summary(game.external_id)) if game.is_final else None
    with db.connection() as conn:
        home_id = entity_repo.resolve_or_create_team(conn, SOURCE, game.home_team)
        away_id = entity_repo.resolve_or_create_team(conn, SOURCE, game.away_team)
        game_id = entity_repo.upsert_game(
            conn, SOURCE, game, home_team_id=home_id, away_team_id=away_id
        )
        if summary is None:
            conn.commit()
            return False

        team_ids = {game.home_team.external_id: home_id, game.away_team.external_id: away_id}
        for team_box in summary.teams:
            team_id = team_ids.get(
                team_box.team.external_id
            ) or entity_repo.resolve_or_create_team(conn, SOURCE, team_box.team)
            stats_repo.upsert_team_game_stats(
                conn, game_id=game_id, team_id=team_id, source=SOURCE, box=team_box
            )
        for line in summary.players:
            team_id = team_ids.get(
                line.team.external_id
            ) or entity_repo.resolve_or_create_team(conn, SOURCE, line.team)
            player_id = entity_repo.resolve_or_create_player(conn, SOURCE, line.player)
            stats_repo.upsert_player_game_stats(
                conn,
                game_id=game_id,
                player_id=player_id,
                team_id=team_id,
                source=SOURCE,
                line=line,
            )
        conn.commit()
    return True
