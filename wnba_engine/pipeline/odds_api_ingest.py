"""the-odds-api game-level sportsbook odds ingestion: paid API (high-quota
plan), moneyline/spread/total lines from up to 32 real bookmakers, plus
real historical archives back to at least 2022-06-01 (verified live) --
unlike balldontlie's /odds (rolling recent window only), the-odds-api's
historical endpoint is this repo's only source of REAL past line
movement.

Reuses sportsbook_game_odds (db/migrations/0014_balldontlie_odds.sql) with
source='the_odds_api' -- see wnba_engine/odds_api/odds_parser.py for why
that schema already fits this provider's payload once requested in
American odds format.

Two entry points:

- snapshot_current_odds: current-odds snapshot (Task 1) -- meant for a
  recurring schedule, same "rolling window, missed capture = lost data"
  cadence as snapshot-kalshi/snapshot-polymarket.
- backfill_history: historical checkpoint sweep (Task 2) -- for each
  canonical game in [since, until] (games.start_time), computes T-7d/
  T-24h/T-1h/closing checkpoint timestamps (matching the line-movement
  cadence ROADMAP.md documents for the private Phase 0 pipeline this is
  modeled on) and queries the historical endpoint at each one. A single
  historical call returns odds for EVERY event live at that timestamp, not
  just the one game the checkpoint was computed from -- rather than
  discard that, any returned event whose commence_time also falls in
  [since, until] is resolved and persisted too (idempotent re-insertion
  across overlapping checkpoint calls is a no-op, not a bug, thanks to
  sportsbook_game_odds' UNIQUE(external_id, captured_at)). Only games
  actually within [since, until] are ever touched -- an event outside that
  window returned by the same API response is ignored, matching the
  design note that this must not blindly ingest everything a historical
  call happens to return.

Games are resolved via the SAME team+date crosswalk pattern balldontlie's
odds ingestion and Kalshi/Polymarket use (entity_repo.find_game_id_by_teams
+ record_crosswalk_mapping on first sight of an event id, then a fast
lookup_internal_id on repeat sight) -- the-odds-api's own event `id` is a
new external id space (a UUID-like string), not shared with any existing
crosswalk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.models.odds_api_events import OddsApiEventRef, ParsedOddsEvent
from wnba_engine.odds_api.client import OddsApiClient
from wnba_engine.odds_api.odds_parser import parse_current_odds_events, parse_historical_odds_events
from wnba_engine.repositories import entity_repo, odds_repo

logger = logging.getLogger(__name__)

SOURCE = "the_odds_api"

# the-odds-api reports commence_time to the second and our own games table
# is populated from ESPN's scoreboard -- a few minutes of slop between
# providers for "the same" game is normal, same order of magnitude as
# balldontlie's GAME_MATCH_WINDOW (6h) and Kalshi/Polymarket's (1 day for
# ticker-date-only matches). the-odds-api gives an exact commence_time, so
# a tighter window is safe and reduces the odds of matching the wrong game
# on a busy multi-game day.
GAME_MATCH_WINDOW = timedelta(hours=3)

# T-7d, T-24h, T-1h, closing (closing = at commence_time itself -- "at or
# shortly after", per ROADMAP.md's documented Phase 0 cadence).
CHECKPOINT_OFFSETS: tuple[timedelta, ...] = (
    timedelta(days=7),
    timedelta(hours=24),
    timedelta(hours=1),
    timedelta(0),
)


@dataclass(frozen=True, slots=True)
class OddsApiIngestResult:
    events_seen: int = 0
    rows_seen: int = 0
    rows_inserted: int = 0
    unresolved_events: int = 0


def snapshot_current_odds(db: Database, client: OddsApiClient) -> OddsApiIngestResult:
    """Snapshot current odds for every WNBA event the-odds-api currently
    lists. One request (verified live: no pagination on this endpoint)."""
    payload = client.fetch_current_odds()
    parsed_events = parse_current_odds_events(payload)
    result = OddsApiIngestResult()
    with db.connection() as conn:
        for parsed in parsed_events:
            outcome = _ingest_event(conn, parsed)
            result = replace(
                result,
                events_seen=result.events_seen + 1,
                rows_seen=result.rows_seen + outcome.rows_seen,
                rows_inserted=result.rows_inserted + outcome.rows_inserted,
                unresolved_events=result.unresolved_events + (0 if outcome.resolved else 1),
            )
        conn.commit()
    return result


@dataclass(frozen=True, slots=True)
class OddsApiHistoryIngestResult:
    games_checked: int = 0
    checkpoints_queried: int = 0
    checkpoints_skipped_future: int = 0
    rows_seen: int = 0
    rows_inserted: int = 0
    unresolved_events: int = 0


def backfill_history(
    db: Database, client: OddsApiClient, since: date, until: date
) -> OddsApiHistoryIngestResult:
    if since > until:
        raise ValueError("since must not be after until")

    since_dt = datetime.combine(since, time.min, tzinfo=UTC)
    until_dt = datetime.combine(until, time.max, tzinfo=UTC)
    with db.connection() as conn:
        games = entity_repo.list_games_in_range(conn, since_dt, until_dt)

    result = OddsApiHistoryIngestResult()
    now = datetime.now(UTC)
    for _game_id, start_time in games:
        result = replace(result, games_checked=result.games_checked + 1)
        for offset in CHECKPOINT_OFFSETS:
            checkpoint_at = start_time - offset
            if checkpoint_at > now:
                # No historical snapshot can exist for a moment that
                # hasn't happened yet (e.g. a --until spanning into the
                # future, or "closing" for a game later today).
                result = replace(
                    result, checkpoints_skipped_future=result.checkpoints_skipped_future + 1
                )
                continue
            result = replace(result, checkpoints_queried=result.checkpoints_queried + 1)
            payload = client.fetch_historical_odds(checkpoint_at)
            parsed_events = parse_historical_odds_events(payload)
            with db.connection() as conn:
                for parsed in parsed_events:
                    if not (since_dt <= parsed.event.commence_time <= until_dt):
                        continue  # outside this backfill's target range -- see module docstring
                    outcome = _ingest_event(conn, parsed)
                    result = replace(
                        result,
                        rows_seen=result.rows_seen + outcome.rows_seen,
                        rows_inserted=result.rows_inserted + outcome.rows_inserted,
                        unresolved_events=result.unresolved_events + (0 if outcome.resolved else 1),
                    )
                conn.commit()
    return result


@dataclass(frozen=True, slots=True)
class _EventIngestOutcome:
    resolved: bool
    rows_seen: int
    rows_inserted: int


def _ingest_event(conn: Connection, parsed: ParsedOddsEvent) -> _EventIngestOutcome:
    """Resolve one event to a canonical game and persist its odds rows.
    Shared by both entry points so the resolve-then-insert-then-count logic
    (and its unresolved-event skip behavior) lives in exactly one place."""
    game_id = _resolve_event_game_id(conn, parsed.event)
    if game_id is None:
        logger.warning(
            "unresolved the_odds_api event external_id=%s (%s vs %s, commence_time=%s) "
            "-- skipping %d odds row(s)",
            parsed.event.external_id,
            parsed.event.home_team,
            parsed.event.away_team,
            parsed.event.commence_time,
            len(parsed.rows),
        )
        return _EventIngestOutcome(resolved=False, rows_seen=0, rows_inserted=0)

    rows_inserted = 0
    for row in parsed.rows:
        if odds_repo.insert_game_odds(conn, game_id=game_id, source=SOURCE, row=row):
            rows_inserted += 1
    return _EventIngestOutcome(
        resolved=True, rows_seen=len(parsed.rows), rows_inserted=rows_inserted
    )


def _resolve_event_game_id(conn: Connection, event: OddsApiEventRef) -> int | None:
    existing = entity_repo.lookup_internal_id(
        conn, SOURCE, entity_repo.ENTITY_GAME, event.external_id
    )
    if existing is not None:
        return existing
    game_id = entity_repo.find_game_id_by_teams(
        conn, event.home_team, event.away_team, event.commence_time, window=GAME_MATCH_WINDOW
    )
    if game_id is None:
        return None
    entity_repo.record_crosswalk_mapping(
        conn, SOURCE, entity_repo.ENTITY_GAME, event.external_id, game_id
    )
    return game_id
