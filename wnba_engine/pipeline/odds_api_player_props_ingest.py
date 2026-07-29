"""the-odds-api PLAYER PROP ingestion.

Closes the gap that made sportsbook_player_prop_odds look sparse: the
game-level integration (wnba_engine/pipeline/odds_api_ingest.py) requests
markets="h2h,spreads,totals" against the BULK odds endpoint, which cannot
return player props at any market list. Props exist only on the per-EVENT
endpoints, so before this module every prop row in the database came from
balldontlie -- 2026 only, a few hundred games.

Writes into the same sportsbook_player_prop_odds table balldontlie's props
use, with source='the_odds_api' and the SAME prop_type vocabulary (see
player_props_parser.prop_type_for_market) so the two sources are directly
comparable rather than two vocabularies in one column.

Two entry points, mirroring odds_api_ingest:

- snapshot_current_props: every currently-listed event. The event list
  itself costs 0 quota, so the only spend is 1 unit per market per event.
- backfill_props_history: T-7d/T-24h/T-1h/closing per canonical game in
  [since, until], the same checkpoint cadence as the game-odds backfill,
  at 10 units per market per event per checkpoint.

QUOTA. This is by far the most expensive thing in the repo: a five-market,
four-checkpoint historical sweep costs 200 units per game (~209k units for
2023-present). Both entry points report units_estimated so a caller can
reconcile against the-odds-api's x-requests-used header.

EVENT IDS. A historical props call is per-event, so the backfill needs the
event id that was valid at each checkpoint. Rather than pay for a
historical event-list call per checkpoint, it reads the ids already in
provider_entity_map from the game-odds backfill. That also handles
the-odds-api re-issuing an id mid-life (see DATA_INVENTORY.md): a game can
map to more than one event id, so each is tried until one returns props.
A game with no mapped event id is skipped and counted -- run
backfill-odds-api-history for that range first.

PLAYERS. the-odds-api carries no player identifier at all; a prop names
its player only in the free-text `description` on each outcome. Resolution
is therefore by name against players.full_name, via the same
find_player_by_name helper (exact, then diacritic-folded) that
Kalshi/Polymarket prop matching uses. Unresolved names are logged and
skipped, never invented as new player rows -- a sportsbook's spelling is
far too thin a basis to originate a canonical identity, and a typo'd name
would otherwise silently fork a player.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.models.odds_api_events import OddsApiEventRef, ParsedPropEvent
from wnba_engine.odds_api.client import OddsApiClient
from wnba_engine.odds_api.odds_parser import parse_current_odds_events
from wnba_engine.odds_api.player_props_parser import (
    REQUESTED_MARKETS,
    parse_current_event_props,
    parse_historical_event_props,
)
from wnba_engine.pipeline.odds_api_ingest import CHECKPOINT_OFFSETS, GAME_MATCH_WINDOW
from wnba_engine.repositories import entity_repo, odds_repo

logger = logging.getLogger(__name__)

SOURCE = "the_odds_api"

# Verified live via the x-requests-last header: 1 unit per market per
# region for current props, 10x that for historical. Used only to report
# an estimate -- the header remains the authority on actual spend.
UNITS_PER_MARKET_CURRENT = 1
UNITS_PER_MARKET_HISTORICAL = 10


@dataclass(frozen=True, slots=True)
class PropIngestResult:
    events_seen: int = 0
    rows_seen: int = 0
    rows_inserted: int = 0
    unresolved_events: int = 0
    unresolved_players: int = 0
    units_estimated: int = 0


def snapshot_current_props(db: Database, client: OddsApiClient) -> PropIngestResult:
    """Current player props for every listed event.

    The event list is fetched from the bulk odds endpoint rather than
    /events: the props call needs each event's teams and commence_time to
    resolve a canonical game anyway, and the bulk call already carries
    them alongside odds this pipeline ignores.
    """
    events = parse_current_odds_events(client.fetch_current_odds())
    result = PropIngestResult()
    for parsed_event in events:
        payload = client.fetch_event_props(
            parsed_event.event.external_id, markets=REQUESTED_MARKETS
        )
        result = replace(
            result,
            events_seen=result.events_seen + 1,
            units_estimated=result.units_estimated
            + len(REQUESTED_MARKETS) * UNITS_PER_MARKET_CURRENT,
        )
        result = _ingest_prop_payload(db, parse_current_event_props(payload), result)
    return result


@dataclass(frozen=True, slots=True)
class PropHistoryIngestResult:
    games_checked: int = 0
    games_without_event_id: int = 0
    checkpoints_queried: int = 0
    checkpoints_skipped_future: int = 0
    # Checkpoints where the-odds-api had not listed the event yet (404).
    # Expected at T-7d for games books post late -- not an error.
    checkpoints_absent: int = 0
    rows_seen: int = 0
    rows_inserted: int = 0
    unresolved_players: int = 0
    units_estimated: int = 0


def backfill_props_history(
    db: Database, client: OddsApiClient, since: date, until: date
) -> PropHistoryIngestResult:
    if since > until:
        raise ValueError("since must not be after until")

    since_dt = datetime.combine(since, time.min, tzinfo=UTC)
    until_dt = datetime.combine(until, time.max, tzinfo=UTC)
    with db.connection() as conn:
        games = entity_repo.list_games_in_range(conn, since_dt, until_dt)

    result = PropHistoryIngestResult()
    now = datetime.now(UTC)
    for game_id, start_time in games:
        result = replace(result, games_checked=result.games_checked + 1)
        with db.connection() as conn:
            event_ids = entity_repo.list_external_ids(
                conn, SOURCE, entity_repo.ENTITY_GAME, game_id
            )
        if not event_ids:
            logger.warning(
                "game_id=%s (start_time=%s) has no the_odds_api event id -- run "
                "backfill-odds-api-history for this range first; skipping props",
                game_id,
                start_time,
            )
            result = replace(result, games_without_event_id=result.games_without_event_id + 1)
            continue

        for offset in CHECKPOINT_OFFSETS:
            checkpoint_at = start_time - offset
            if checkpoint_at > now:
                result = replace(
                    result, checkpoints_skipped_future=result.checkpoints_skipped_future + 1
                )
                continue
            result = _backfill_one_checkpoint(db, client, game_id, event_ids, checkpoint_at, result)
    return result


def _backfill_one_checkpoint(
    db: Database,
    client: OddsApiClient,
    game_id: int,
    event_ids: tuple[str, ...],
    checkpoint_at: datetime,
    result: PropHistoryIngestResult,
) -> PropHistoryIngestResult:
    """Query one checkpoint, trying each of the game's event ids until one
    yields props.

    An event id is only valid for the window the-odds-api actually listed
    that event, so a checkpoint outside it returns None (a 404 upstream --
    see fetch_historical_event_props). That is routine, not a failure: a
    T-7d checkpoint on a game the books posted late has no snapshot to
    fetch, and counting it as `checkpoints_absent` keeps that visible
    without stopping the sweep.

    Multiple ids only happen when the-odds-api re-issued one mid-life, in
    which case at most one is valid at any given timestamp -- so an absent
    or empty response from the first is expected, and the loop moves on
    rather than concluding the game had no props.
    """
    for event_id in event_ids:
        result = replace(
            result,
            checkpoints_queried=result.checkpoints_queried + 1,
            units_estimated=result.units_estimated
            + len(REQUESTED_MARKETS) * UNITS_PER_MARKET_HISTORICAL,
        )
        payload = client.fetch_historical_event_props(
            event_id, checkpoint_at, markets=REQUESTED_MARKETS
        )
        if payload is None:
            result = replace(result, checkpoints_absent=result.checkpoints_absent + 1)
            continue
        parsed = parse_historical_event_props(payload)
        if not parsed.props:
            continue
        rows_seen, rows_inserted, unresolved = _persist_props(db, game_id, parsed)
        return replace(
            result,
            rows_seen=result.rows_seen + rows_seen,
            rows_inserted=result.rows_inserted + rows_inserted,
            unresolved_players=result.unresolved_players + unresolved,
        )
    return result


def _ingest_prop_payload(
    db: Database, parsed: ParsedPropEvent, result: PropIngestResult
) -> PropIngestResult:
    with db.connection() as conn:
        game_id = _resolve_event_game_id(conn, parsed.event)
        conn.commit()
    if game_id is None:
        logger.warning(
            "unresolved the_odds_api event external_id=%s (%s vs %s, commence_time=%s) "
            "-- skipping %d prop row(s)",
            parsed.event.external_id,
            parsed.event.home_team,
            parsed.event.away_team,
            parsed.event.commence_time,
            len(parsed.props),
        )
        return replace(result, unresolved_events=result.unresolved_events + 1)

    rows_seen, rows_inserted, unresolved = _persist_props(db, game_id, parsed)
    return replace(
        result,
        rows_seen=result.rows_seen + rows_seen,
        rows_inserted=result.rows_inserted + rows_inserted,
        unresolved_players=result.unresolved_players + unresolved,
    )


def _persist_props(db: Database, game_id: int, parsed: ParsedPropEvent) -> tuple[int, int, int]:
    """Resolve each prop's player by name and insert. Returns
    (rows_seen, rows_inserted, unresolved_players)."""
    rows_seen = 0
    rows_inserted = 0
    unresolved = 0
    unresolved_names: set[str] = set()
    with db.connection() as conn:
        for prop in parsed.props:
            # allow_reversed: bovada writes some props "Last First" while
            # every other book uses "First Last" -- see find_player_by_name.
            player_id = entity_repo.find_player_by_name(
                conn, prop.player_name, allow_reversed=True
            )
            if player_id is None:
                unresolved += 1
                unresolved_names.add(prop.player_name)
                continue
            rows_seen += 1
            if odds_repo.insert_player_prop_odds(
                conn, game_id=game_id, player_id=player_id, source=SOURCE, row=prop.row
            ):
                rows_inserted += 1
        conn.commit()
    if unresolved_names:
        logger.warning(
            "game_id=%s: %d prop row(s) skipped, unresolved player name(s): %s",
            game_id,
            unresolved,
            ", ".join(sorted(unresolved_names)),
        )
    return rows_seen, rows_inserted, unresolved


def _resolve_event_game_id(conn: Connection, event: OddsApiEventRef) -> int | None:
    """Same resolve-then-record pattern as odds_api_ingest, reused rather
    than shared so the props pipeline doesn't depend on that module's
    private helper."""
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
