"""ESPN transactions ingestion: roster moves (signings, waivers, releases,
trades, front-office/coaching hires) at season granularity.

Season-level, not date-ranged or per-game: ESPN's transactions endpoint is
queried by `season` (see espn/client.py::fetch_transactions), looping pages
only when the response's `pageCount` says there's more than one (confirmed
live: 2022-2024 fit in a single page at limit=200; 2025 needed 2 pages).

Team resolution uses lookup_internal_id directly (read-only, never
creates) rather than resolve_or_create_team -- ESPN teams should already
exist from scoreboard ingestion by the time this ever runs; a miss is
logged and the row is still written with team_id=NULL + the raw team name
preserved (see 0020_player_transactions.sql), never dropped.

Player resolution is genuinely best-effort: transaction_classifier extracts
a raw_player_name from the free-text description (or None for a
coaching/front-office move), and entity_repo.find_player_by_name resolves
it to a canonical player when possible. A name that doesn't resolve is
still written with raw_player_name populated and player_id=NULL -- never
silently dropped, and never blocks the type/description/date/team fields
from being written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from wnba_engine.db.pool import Database
from wnba_engine.espn.client import EspnClient
from wnba_engine.espn.transaction_classifier import (
    classify_transaction_type,
    extract_raw_player_name,
)
from wnba_engine.espn.transactions_parser import page_count, parse_transactions_page
from wnba_engine.repositories import entity_repo, transactions_repo

logger = logging.getLogger(__name__)

SOURCE = "espn"
SOURCE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/transactions"


@dataclass(frozen=True, slots=True)
class EspnTransactionsIngestResult:
    transactions_seen: int = 0
    rows_inserted: int = 0
    rows_skipped_duplicate: int = 0
    teams_resolved: int = 0
    teams_unresolved: int = 0
    players_resolved: int = 0
    players_raw_only: int = 0
    players_unclassified: int = 0

    def merged_with(self, other: EspnTransactionsIngestResult) -> EspnTransactionsIngestResult:
        return EspnTransactionsIngestResult(
            transactions_seen=self.transactions_seen + other.transactions_seen,
            rows_inserted=self.rows_inserted + other.rows_inserted,
            rows_skipped_duplicate=self.rows_skipped_duplicate + other.rows_skipped_duplicate,
            teams_resolved=self.teams_resolved + other.teams_resolved,
            teams_unresolved=self.teams_unresolved + other.teams_unresolved,
            players_resolved=self.players_resolved + other.players_resolved,
            players_raw_only=self.players_raw_only + other.players_raw_only,
            players_unclassified=self.players_unclassified + other.players_unclassified,
        )


def backfill_season(db: Database, client: EspnClient, season: int) -> EspnTransactionsIngestResult:
    """Ingest every transaction ESPN reports for one season, looping pages
    as needed. Safe to re-run: duplicate rows (by the UNIQUE constraint on
    team_id/transaction_date/description) are silently skipped, not
    re-counted as inserts.
    """
    result = EspnTransactionsIngestResult()
    first_page = client.fetch_transactions(season, page=1)
    total_pages = page_count(first_page)
    result = _ingest_page(db, result, first_page)

    for page_number in range(2, total_pages + 1):
        page_payload = client.fetch_transactions(season, page=page_number)
        result = _ingest_page(db, result, page_payload)

    return result


def _ingest_page(
    db: Database, result: EspnTransactionsIngestResult, payload: object
) -> EspnTransactionsIngestResult:
    raw_transactions = parse_transactions_page(payload)
    with db.connection() as conn:
        for raw in raw_transactions:
            result = replace(result, transactions_seen=result.transactions_seen + 1)

            team_id = entity_repo.lookup_internal_id(
                conn, SOURCE, entity_repo.ENTITY_TEAM, raw.team_external_id
            )
            if team_id is None:
                logger.warning(
                    "unresolved team external_id=%s name=%s for espn transaction "
                    "date=%s -- storing with team_id=NULL",
                    raw.team_external_id,
                    raw.team_name,
                    raw.transaction_date.isoformat(),
                )
                result = replace(result, teams_unresolved=result.teams_unresolved + 1)
            else:
                result = replace(result, teams_resolved=result.teams_resolved + 1)

            transaction_type = classify_transaction_type(raw.description)
            raw_player_name = extract_raw_player_name(raw.description)

            player_id: int | None = None
            if raw_player_name is None:
                result = replace(result, players_unclassified=result.players_unclassified + 1)
            else:
                player_id = entity_repo.find_player_by_name(conn, raw_player_name)
                if player_id is None:
                    result = replace(result, players_raw_only=result.players_raw_only + 1)
                else:
                    result = replace(result, players_resolved=result.players_resolved + 1)

            inserted = transactions_repo.insert_transaction(
                conn,
                transaction_date=raw.transaction_date,
                team_id=team_id,
                raw_team_name=raw.team_name,
                player_id=player_id,
                raw_player_name=raw_player_name,
                transaction_type=transaction_type,
                description=raw.description,
                source=SOURCE_URL,
            )
            if inserted:
                result = replace(result, rows_inserted=result.rows_inserted + 1)
            else:
                result = replace(result, rows_skipped_duplicate=result.rows_skipped_duplicate + 1)
        conn.commit()
    return result
