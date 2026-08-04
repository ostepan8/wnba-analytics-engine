"""stats.wnba.com ingestion: player-attributed plays and shot locations.

Unblocks FEATURE_ROADMAP.md ss9's one blocked row. Play-by-play had no
player ids because balldontlie does not publish them; the league's own feed
does, on 97% of events, back to 1997.

IDENTITY IS THE WHOLE JOB HERE. stats.wnba.com is a FOURTH id space (after
ESPN, balldontlie and the sportsbooks) and nothing in this database maps it,
so every game, team and player has to resolve through the canonical
crosswalk before a row can be written:

- **games** by (date, both teams), because the feed's GAME_ID shares nothing
  with ours. The game log gives two rows per game -- one per team -- and the
  MATCHUP string carries which side was home.
- **teams** by abbreviation, through `team_matching`: five of thirteen
  disagree with ours and the difference is not derivable.
- **players** through `resolve_or_create_player_by_name`, the same helper
  balldontlie uses, so a stats.wnba.com id joins onto the player ESPN's box
  scores already created instead of forking a duplicate.

Plays are written into the existing `game_plays` table under
source='wnba_stats' rather than a new one -- that is what the source column
and UNIQUE(game_id, sequence, source) exist for, and it leaves every
existing query untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.errors import ProviderRequestError, ProviderValidationError
from wnba_engine.repositories import entity_repo, stats_play_repo
from wnba_engine.wnba_stats import parser
from wnba_engine.wnba_stats.client import PROVIDER, WnbaStatsClient
from wnba_engine.wnba_stats.team_matching import parse_matchup

logger = logging.getLogger(__name__)

#: The feed dates a game by its local calendar day; our start_time is UTC,
#: so an evening tip lands on the following UTC date. A day either side
#: covers that without being loose enough to catch a different meeting.
GAME_DATE_WINDOW = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class WnbaStatsIngestResult:
    games_seen: int = 0
    games_failed: int = 0
    games_resolved: int = 0
    games_skipped: int = 0
    plays_inserted: int = 0
    shots_inserted: int = 0
    players_resolved: int = 0
    unresolved_games: int = 0


def ingest_season(
    db: Database,
    client: WnbaStatsClient,
    season: int,
    *,
    resume: bool = True,
    include_shots: bool = True,
    game_limit: int | None = None,
) -> WnbaStatsIngestResult:
    """Ingest one season's plays and shots."""
    refs = parser.parse_game_log(client.fetch_game_log(season), season=season)
    by_game: dict[str, list] = {}
    for ref in refs:
        by_game.setdefault(ref.game_id, []).append(ref)

    with db.connection() as conn:
        done_plays = stats_play_repo.games_with_source(conn, PROVIDER) if resume else frozenset()
        done_shots = stats_play_repo.games_with_shots(conn, PROVIDER) if resume else frozenset()

    seen = resolved = skipped = plays = shots = unresolved = failed = 0
    players: set[int] = set()
    items = list(by_game.items())
    if game_limit is not None:
        items = items[:game_limit]

    for stats_game_id, group in items:
        seen += 1
        with db.connection() as conn:
            game_id = _resolve_game(conn, group)
        if game_id is None:
            unresolved += 1
            continue
        resolved += 1
        if game_id in done_plays and (not include_shots or game_id in done_shots):
            skipped += 1
            continue

        if game_id not in done_plays:
            # A single game 500s or times out often enough over thousands of
            # requests that aborting the sweep would make a full backfill
            # impossible. Counted and logged, never silent -- a systematic
            # failure shows up as a large games_failed rather than as a
            # season that quietly came up short.
            try:
                events = parser.parse_play_by_play(client.fetch_play_by_play(stats_game_id))
            except (ProviderRequestError, ProviderValidationError) as exc:
                failed += 1
                logger.warning("wnba_stats plays failed for %s: %s", stats_game_id, exc)
                events = ()
            with db.connection() as conn:
                rows, touched = _play_rows(conn, game_id, events)
                plays += stats_play_repo.insert_plays(conn, rows)
                players |= touched
                conn.commit()

        if include_shots and game_id not in done_shots:
            try:
                attempts = parser.parse_shot_chart(
                    client.fetch_shot_chart(stats_game_id, season),
                )
            except (ProviderRequestError, ProviderValidationError) as exc:
                logger.warning("wnba_stats shots failed for %s: %s", stats_game_id, exc)
                attempts = ()
            with db.connection() as conn:
                rows, touched = _shot_rows(conn, game_id, attempts)
                shots += stats_play_repo.insert_shots(conn, rows)
                players |= touched
                conn.commit()

    logger.info(
        "wnba_stats %s: %d game(s) seen, %d resolved, %d skipped, %d unresolved, "
        "%d failed, %d play(s), %d shot(s), %d distinct player(s)",
        season, seen, resolved, skipped, unresolved, failed, plays, shots, len(players),
    )
    return WnbaStatsIngestResult(
        seen, failed, resolved, skipped, plays, shots, len(players), unresolved
    )


def _resolve_game(conn: Connection, group: Sequence[parser.StatsGameRef]) -> int | None:
    """Canonical game id from the feed's own date and matchup.

    Needs both team rows, which is why the caller groups by GAME_ID first --
    one row names only one side, and `find_game_id_by_teams` wants the pair.
    """
    ref = group[0]
    teams = parse_matchup(ref.matchup)
    if teams is None:
        return None
    home, away = teams
    near = datetime.combine(ref.game_date, time(12, 0), tzinfo=UTC)
    home_id = entity_repo.find_team_by_abbreviation(conn, home)
    away_id = entity_repo.find_team_by_abbreviation(conn, away)
    if home_id is None or away_id is None:
        return None
    return entity_repo.find_game_id_by_teams(
        conn,
        _team_name(conn, home_id),
        _team_name(conn, away_id),
        near,
        window=GAME_DATE_WINDOW,
    )


def _team_name(conn: Connection, team_id: int) -> str:
    row = conn.execute("SELECT name FROM teams WHERE id = %s", (team_id,)).fetchone()
    return str(row[0]) if row else ""


def _player_id(
    conn: Connection, external_id: str | None, name: str | None
) -> int | None:
    """Resolve one participant, or None when the slot was empty.

    A name is required as well as an id: the crosswalk is keyed on the
    provider id, but on FIRST sight there is nothing to look up, and the
    name is what joins this player onto the canonical one ESPN created.
    """
    if not external_id or not name:
        return None
    return entity_repo.resolve_or_create_player_by_name(
        conn, PROVIDER, external_id, name,
        position=None, height=None, weight=None,
        jersey_number=None, college=None, age=None,
    )


def _play_rows(
    conn: Connection, game_id: int, events: Sequence[parser.StatsPlay]
) -> tuple[list[tuple], set[int]]:
    rows: list[tuple] = []
    touched: set[int] = set()
    # The feed populates SCORE only on scoring events, but game_plays.
    # home_score/away_score are NOT NULL and the balldontlie rows carry a
    # running score on every play. Carrying the last known value forward
    # matches that and is the honest reading: it is the score AS AT this
    # play, which is what a mid-game query wants.
    home_running, away_running = 0, 0
    for event in events:
        p1 = _player_id(conn, event.player1_external_id, event.player1_name)
        p2 = _player_id(conn, event.player2_external_id, event.player2_name)
        p3 = _player_id(conn, event.player3_external_id, event.player3_name)
        touched |= {p for p in (p1, p2, p3) if p is not None}
        home, away = _split_score(event.score)
        scored = home is not None and away is not None
        # Points added by THIS event, derived from the running total rather
        # than read: the feed gives a cumulative score, not a delta.
        value = 0
        if scored:
            value = (home - home_running) + (away - away_running)
            home_running, away_running = home, away
        rows.append(
            (
                game_id, None, PROVIDER, event.event_num, event.period, event.clock,
                parser.event_label(event.event_type), event.description,
                home_running, away_running,
                # SCORE appearing at all is the provider's own signal that
                # this event changed it, which is more reliable than
                # inferring from the event type (a missed free throw is
                # still EVENTMSGTYPE 3).
                scored,
                value,
                p1, p2, p3, event.event_type, event.event_action_type,
            )
        )
    return rows, touched


def _shot_rows(
    conn: Connection, game_id: int, attempts: Sequence[parser.StatsShot]
) -> tuple[list[tuple], set[int]]:
    rows: list[tuple] = []
    touched: set[int] = set()
    for shot in attempts:
        player = _player_id(conn, shot.player_external_id, shot.player_name)
        if player is not None:
            touched.add(player)
        rows.append(
            (
                game_id, player, None, PROVIDER, shot.game_event_id, shot.period,
                shot.seconds_remaining, shot.action_type, shot.shot_type,
                shot.shot_zone_basic, shot.shot_zone_area, shot.shot_zone_range,
                shot.shot_distance, shot.loc_x, shot.loc_y, shot.made,
            )
        )
    return rows, touched


def _split_score(score: str | None) -> tuple[int | None, int | None]:
    """'54 - 61' -> (54, 61); anything else -> (None, None).

    The feed populates SCORE only on scoring plays and leaves it null
    otherwise, so most events legitimately have no score attached.
    """
    if not score or "-" not in score:
        return None, None
    left, _, right = score.partition("-")
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None, None
