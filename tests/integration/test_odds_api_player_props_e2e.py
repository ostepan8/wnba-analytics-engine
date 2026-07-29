"""End-to-end integration tests: the-odds-api PLAYER PROP pipelines ->
real Postgres.

Requires a reachable *test* Postgres database (docker compose up -d
provisions one). Skips gracefully when unavailable. Network calls are
replayed from fixtures trimmed from real live-captured event-odds payloads
(see tests/unit/odds_api/test_odds_api_player_props_parser.py for
provenance) via fake clients, so results are deterministic.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from wnba_engine.models.games import GameStatus, ScoreboardGame, SeasonType, TeamRef
from wnba_engine.pipeline.odds_api_player_props_ingest import (
    backfill_props_history,
    snapshot_current_props,
)
from wnba_engine.repositories import entity_repo

pytestmark = pytest.mark.integration

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

PROPS_EVENT_ID = "c01616be622aa0fcab0ac0351d05e264"
HISTORICAL_EVENT_ID = "bd98c3a50c01fe9eaef23ff1dea90934"


def load_fixture(name: str) -> object:
    return json.loads((_FIXTURES_DIR / name).read_text())


def _seed_game(
    conn,
    *,
    external_id: str,
    home_name: str,
    away_name: str,
    start_time: datetime,
    status: GameStatus = GameStatus.SCHEDULED,
) -> int:
    home_ref = TeamRef(
        external_id=f"{external_id}-home", name=home_name, abbreviation=home_name[:3].upper()
    )
    away_ref = TeamRef(
        external_id=f"{external_id}-away", name=away_name, abbreviation=away_name[:3].upper()
    )
    home_id = entity_repo.resolve_or_create_team(conn, "espn", home_ref)
    away_id = entity_repo.resolve_or_create_team(conn, "espn", away_ref)
    return entity_repo.upsert_game(
        conn,
        "espn",
        ScoreboardGame(
            external_id=external_id,
            start_time=start_time,
            season=start_time.year,
            season_type=SeasonType.REGULAR_SEASON,
            status=status,
            home_team=home_ref,
            away_team=away_ref,
            home_score=None,
            away_score=None,
        ),
        home_team_id=home_id,
        away_team_id=away_id,
    )


def _seed_players(conn, names: list[str]) -> None:
    """Props resolve by name against players.full_name, so the canonical
    players must already exist -- exactly as they would from ESPN box
    scores in the real pipeline."""
    for i, name in enumerate(names):
        entity_repo.resolve_or_create_player_by_name(
            conn,
            "espn",
            external_id=f"seed-player-{i}",
            full_name=name,
            position=None,
            height=None,
            weight=None,
            jersey_number=None,
            college=None,
            age=None,
        )


CURRENT_EVENT_PLAYERS = [
    "Allisha Gray",
    "Angel Reese",
    "Azzi Fudd",
    "Jessica Shepard",
    "Jordin Canada",
    "Naz Hillmon",
    "Paige Bueckers",
    "Rhyne Howard",
]


class FakePropsClient:
    """fetch_current_odds drives event discovery; fetch_event_props
    returns the real trimmed props payload."""

    def __init__(self) -> None:
        self.prop_calls: list[tuple[str, tuple[str, ...]]] = []

    def fetch_current_odds(self) -> object:
        props = load_fixture("odds_api_player_props.json")
        # The bulk odds endpoint's event shape, carrying the same identity
        # as the props fixture so the crosswalk resolves to one game.
        return [
            {
                "id": props["id"],
                "sport_key": "basketball_wnba",
                "sport_title": "WNBA",
                "commence_time": props["commence_time"],
                "home_team": props["home_team"],
                "away_team": props["away_team"],
                "bookmakers": [],
            }
        ]

    def fetch_event_props(self, event_id: str, *, markets) -> object:
        self.prop_calls.append((event_id, tuple(markets)))
        return load_fixture("odds_api_player_props.json")


def test_snapshot_current_props_end_to_end(clean_db):
    with clean_db.connection() as conn:
        game_id = _seed_game(
            conn,
            external_id="espn-props-1",
            home_name="Dallas Wings",
            away_name="Atlanta Dream",
            start_time=datetime(2026, 7, 30, 0, 0, 0, tzinfo=UTC),
        )
        _seed_players(conn, CURRENT_EVENT_PLAYERS)
        conn.commit()

    client = FakePropsClient()
    result = snapshot_current_props(clean_db, client)

    assert result.events_seen == 1
    assert result.unresolved_events == 0
    assert result.unresolved_players == 0
    assert result.rows_inserted > 0

    with clean_db.connection() as conn:
        rows = conn.execute(
            "SELECT prop_type, market_type, source, over_odds, under_odds "
            "FROM sportsbook_player_prop_odds WHERE game_id = %s",
            (game_id,),
        ).fetchall()

    assert len(rows) == result.rows_inserted
    assert {r[2] for r in rows} == {"the_odds_api"}
    assert {r[1] for r in rows} == {"over_under"}
    # Both sides of every line survived the Over/Under collapse.
    assert all(r[3] is not None and r[4] is not None for r in rows)


def test_snapshot_requests_the_five_configured_markets(clean_db):
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-props-markets",
            home_name="Dallas Wings",
            away_name="Atlanta Dream",
            start_time=datetime(2026, 7, 30, 0, 0, 0, tzinfo=UTC),
        )
        _seed_players(conn, CURRENT_EVENT_PLAYERS)
        conn.commit()

    client = FakePropsClient()
    snapshot_current_props(clean_db, client)

    assert len(client.prop_calls) == 1
    event_id, markets = client.prop_calls[0]
    assert event_id == PROPS_EVENT_ID
    assert markets == (
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_points_rebounds_assists",
    )


def test_prop_types_match_balldontlie_vocabulary(clean_db):
    """Both sources share one table -- a query on prop_type='points' must
    see the-odds-api rows too."""
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-props-vocab",
            home_name="Dallas Wings",
            away_name="Atlanta Dream",
            start_time=datetime(2026, 7, 30, 0, 0, 0, tzinfo=UTC),
        )
        _seed_players(conn, CURRENT_EVENT_PLAYERS)
        conn.commit()

    snapshot_current_props(clean_db, FakePropsClient())

    with clean_db.connection() as conn:
        prop_types = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT prop_type FROM sportsbook_player_prop_odds"
            ).fetchall()
        }

    assert prop_types <= {
        "points",
        "rebounds",
        "assists",
        "threes",
        "points_rebounds_assists",
    }
    assert "points" in prop_types


def test_snapshot_is_idempotent(clean_db):
    """Re-running the same snapshot must not duplicate rows --
    UNIQUE(external_id, captured_at) plus a per-prop external_id."""
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-props-idem",
            home_name="Dallas Wings",
            away_name="Atlanta Dream",
            start_time=datetime(2026, 7, 30, 0, 0, 0, tzinfo=UTC),
        )
        _seed_players(conn, CURRENT_EVENT_PLAYERS)
        conn.commit()

    first = snapshot_current_props(clean_db, FakePropsClient())
    second = snapshot_current_props(clean_db, FakePropsClient())

    assert first.rows_inserted > 0
    assert second.rows_inserted == 0
    assert second.rows_seen == first.rows_seen


def test_unresolved_player_is_skipped_not_invented(clean_db):
    """A sportsbook's spelling is too thin to originate a canonical
    player -- an unknown name must be skipped, never created."""
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-props-unresolved",
            home_name="Dallas Wings",
            away_name="Atlanta Dream",
            start_time=datetime(2026, 7, 30, 0, 0, 0, tzinfo=UTC),
        )
        # Deliberately seed only SOME of the fixture's players.
        _seed_players(conn, CURRENT_EVENT_PLAYERS[:2])
        players_before = conn.execute("SELECT count(*) FROM players").fetchone()[0]
        conn.commit()

    result = snapshot_current_props(clean_db, FakePropsClient())

    with clean_db.connection() as conn:
        players_after = conn.execute("SELECT count(*) FROM players").fetchone()[0]

    assert result.unresolved_players > 0
    assert players_after == players_before  # nothing invented


class FakeHistoricalPropsClient:
    def __init__(self, absent_before: datetime | None = None) -> None:
        self.calls: list[tuple[str, datetime]] = []
        # Checkpoints before this instant return None, mimicking the 404
        # the-odds-api gives for an event it hadn't listed yet.
        self._absent_before = absent_before

    def fetch_historical_event_props(
        self, event_id: str, at: datetime, *, markets
    ) -> object | None:
        del markets
        self.calls.append((event_id, at))
        if self._absent_before is not None and at < self._absent_before:
            return None
        return load_fixture("odds_api_historical_player_props.json")


def test_backfill_props_history_uses_crosswalk_event_ids(clean_db):
    """Event ids come from provider_entity_map (written by the game-odds
    backfill), not a paid historical event-list call."""
    start_time = datetime(2025, 8, 15, 23, 30, 0, tzinfo=UTC)
    with clean_db.connection() as conn:
        game_id = _seed_game(
            conn,
            external_id="espn-props-hist",
            home_name="Chicago Sky",
            away_name="Golden State Valkyries",
            start_time=start_time,
            status=GameStatus.FINAL,
        )
        _seed_players(
            conn,
            ["Kamilla Cardoso", "Ariel Atkins", "Elizabeth Williams", "Veronica Burton"],
        )
        entity_repo.record_crosswalk_mapping(
            conn, "the_odds_api", entity_repo.ENTITY_GAME, HISTORICAL_EVENT_ID, game_id
        )
        conn.commit()

    client = FakeHistoricalPropsClient()
    result = backfill_props_history(clean_db, client, date(2025, 8, 15), date(2025, 8, 15))

    assert result.games_checked == 1
    assert result.games_without_event_id == 0
    assert result.checkpoints_queried == 4  # T-7d / T-24h / T-1h / closing
    assert result.rows_inserted > 0
    assert all(event_id == HISTORICAL_EVENT_ID for event_id, _ in client.calls)


def test_backfill_skips_game_with_no_event_id(clean_db):
    """Without a mapped event id there is nothing to query -- the game is
    reported rather than silently producing zero props."""
    with clean_db.connection() as conn:
        _seed_game(
            conn,
            external_id="espn-props-noevent",
            home_name="Chicago Sky",
            away_name="Golden State Valkyries",
            start_time=datetime(2025, 8, 15, 23, 30, 0, tzinfo=UTC),
            status=GameStatus.FINAL,
        )
        conn.commit()

    client = FakeHistoricalPropsClient()
    result = backfill_props_history(clean_db, client, date(2025, 8, 15), date(2025, 8, 15))

    assert result.games_checked == 1
    assert result.games_without_event_id == 1
    assert result.checkpoints_queried == 0
    assert client.calls == []


def test_backfill_estimates_quota_at_ten_units_per_market(clean_db):
    """Historical props cost 10x current (verified live) -- the estimate
    exists so a caller can reconcile against x-requests-used before
    committing to a season-long sweep."""
    with clean_db.connection() as conn:
        game_id = _seed_game(
            conn,
            external_id="espn-props-quota",
            home_name="Chicago Sky",
            away_name="Golden State Valkyries",
            start_time=datetime(2025, 8, 15, 23, 30, 0, tzinfo=UTC),
            status=GameStatus.FINAL,
        )
        entity_repo.record_crosswalk_mapping(
            conn, "the_odds_api", entity_repo.ENTITY_GAME, HISTORICAL_EVENT_ID, game_id
        )
        conn.commit()

    result = backfill_props_history(
        clean_db, FakeHistoricalPropsClient(), date(2025, 8, 15), date(2025, 8, 15)
    )

    # 4 checkpoints x 5 markets x 10 units
    assert result.units_estimated == 200


def test_backfill_survives_checkpoint_where_event_was_not_listed_yet(clean_db):
    """The regression that killed the first live run: an event id is only
    valid while the-odds-api actually listed that event, so a T-7d
    checkpoint on a late-posted game 404s. That must count as absent and
    let the sweep continue, not abort the whole backfill.
    """
    start_time = datetime(2025, 8, 15, 23, 30, 0, tzinfo=UTC)
    with clean_db.connection() as conn:
        game_id = _seed_game(
            conn,
            external_id="espn-props-absent",
            home_name="Chicago Sky",
            away_name="Golden State Valkyries",
            start_time=start_time,
            status=GameStatus.FINAL,
        )
        _seed_players(
            conn,
            ["Kamilla Cardoso", "Ariel Atkins", "Elizabeth Williams", "Veronica Burton"],
        )
        entity_repo.record_crosswalk_mapping(
            conn, "the_odds_api", entity_repo.ENTITY_GAME, HISTORICAL_EVENT_ID, game_id
        )
        conn.commit()

    # Event only listed from T-24h onward -- the T-7d checkpoint is absent.
    client = FakeHistoricalPropsClient(absent_before=start_time - timedelta(hours=25))
    result = backfill_props_history(clean_db, client, date(2025, 8, 15), date(2025, 8, 15))

    assert result.checkpoints_queried == 4
    assert result.checkpoints_absent == 1
    assert result.rows_inserted > 0  # the other three checkpoints still landed
