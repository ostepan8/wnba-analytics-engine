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

# Stats-table lineage label only ("this data came from ESPN's site API") --
# NOT the provider_entity_map crosswalk key. Kept constant across leagues
# on purpose: box-score tables are keyed by OUR OWN internal game/team/
# player ids, not external ones, so there is no cross-league collision
# risk here the way there was in the crosswalk (see espn/client.py's
# provider split). Crosswalk calls below use `client.provider` instead,
# which IS league-scoped ("espn" / "espn_nba").
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


def sync_date(
    db: Database, client: EspnClient, day: date, *, league: str = "wnba"
) -> EspnIngestResult:
    """Ingest all games (and box scores for finished games) for one date.

    `client` must already be constructed for the same `league` (its base
    URL determines which sport's scoreboard is fetched) -- `league` here
    only tags the canonical rows this run writes.
    """
    games = parse_scoreboard(client.fetch_scoreboard(day), league=league)
    result = EspnIngestResult(games_seen=len(games))
    for game in games:
        try:
            ingested_box = _ingest_game(db, client, game, league=league)
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


def backfill(
    db: Database, client: EspnClient, since: date, until: date, *, league: str = "wnba"
) -> EspnIngestResult:
    """Ingest every date in [since, until], inclusive."""
    if since > until:
        raise ValueError(f"since ({since}) must not be after until ({until})")
    result = EspnIngestResult()
    day = since
    while day <= until:
        try:
            result = result.merged_with(sync_date(db, client, day, league=league))
        except WnbaEngineError:
            # A whole-date failure (scoreboard fetch/parse) is one failure unit.
            logger.exception("failed to ingest scoreboard date=%s", day.isoformat())
            result = replace(result, failures=result.failures + 1)
        day += timedelta(days=1)
    return result


def _ingest_game(
    db: Database, client: EspnClient, game: ScoreboardGame, *, league: str = "wnba"
) -> bool:
    """Upsert one game (+ box score when final). Returns True if box ingested."""
    summary = (
        parse_summary(client.fetch_summary(game.external_id), league=league)
        if game.is_final
        else None
    )
    provider = client.provider
    with db.connection() as conn:
        home_id = entity_repo.resolve_or_create_team(conn, provider, game.home_team)
        away_id = entity_repo.resolve_or_create_team(conn, provider, game.away_team)
        game_id = entity_repo.upsert_game(
            conn, provider, game, home_team_id=home_id, away_team_id=away_id
        )
        if summary is None:
            conn.commit()
            return False

        entity_repo.update_game_venue_info(
            conn, game_id, venue_name=summary.venue_name, attendance=summary.attendance
        )
        stats_repo.replace_game_officials(conn, game_id=game_id, officials=summary.officials)

        team_ids = {game.home_team.external_id: home_id, game.away_team.external_id: away_id}
        for team_box in summary.teams:
            team_id = team_ids.get(team_box.team.external_id) or entity_repo.resolve_or_create_team(
                conn, provider, team_box.team
            )
            stats_repo.upsert_team_game_stats(
                conn, game_id=game_id, team_id=team_id, source=SOURCE, box=team_box
            )
        for line in summary.players:
            team_id = team_ids.get(line.team.external_id) or entity_repo.resolve_or_create_team(
                conn, provider, line.team
            )
            player_id = entity_repo.resolve_or_create_player(conn, provider, line.player)
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
