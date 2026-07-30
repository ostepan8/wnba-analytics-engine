"""End-to-end: prop quotes -> open/close pairing -> CLV report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wnba_engine.models.games import GameStatus, ScoreboardGame, SeasonType, TeamRef
from wnba_engine.pipeline.clv_report import build_clv_report
from wnba_engine.repositories import clv_repo, entity_repo

pytestmark = pytest.mark.integration

TIP = datetime(2026, 7, 20, 23, 0, tzinfo=UTC)


def _seed_game(conn) -> tuple[int, int]:
    home = TeamRef(external_id="clv-h", name="Home Team", abbreviation="HOM")
    away = TeamRef(external_id="clv-a", name="Away Team", abbreviation="AWY")
    home_id = entity_repo.resolve_or_create_team(conn, "espn", home)
    away_id = entity_repo.resolve_or_create_team(conn, "espn", away)
    game_id = entity_repo.upsert_game(
        conn,
        "espn",
        ScoreboardGame(
            external_id="clv-g1", start_time=TIP, season=2026,
            season_type=SeasonType.REGULAR_SEASON, status=GameStatus.FINAL,
            home_team=home, away_team=away, home_score=80, away_score=75,
        ),
        home_team_id=home_id, away_team_id=away_id,
    )
    player_id = entity_repo.resolve_or_create_player_by_name(
        conn, "espn", external_id="clv-p1", full_name="Test Player",
        position=None, height=None, weight=None, jersey_number=None, college=None, age=None,
    )
    return game_id, player_id


def _insert_prop(conn, game_id, player_id, *, at, over, under, line=8.5, vendor="fanduel"):
    conn.execute(
        "INSERT INTO sportsbook_player_prop_odds (source, external_id, game_id, player_id, "
        "vendor, prop_type, line_value, market_type, over_odds, under_odds, captured_at) "
        "VALUES ('the_odds_api', %s, %s, %s, %s, 'rebounds', %s, 'over_under', %s, %s, %s)",
        (f"{vendor}:{at.isoformat()}", game_id, player_id, vendor, line, over, under, at),
    )


def test_open_close_pairing_uses_first_and_last_pregame_quote(clean_db):
    with clean_db.connection() as conn:
        game_id, player_id = _seed_game(conn)
        for hours, (o, u) in ((10, (-110, -110)), (5, (-120, 100)), (1, (-140, 120))):
            _insert_prop(conn, game_id, player_id, at=TIP - timedelta(hours=hours), over=o, under=u)
        # In-play: must be ignored, it already knows part of the answer.
        _insert_prop(conn, game_id, player_id, at=TIP + timedelta(minutes=30), over=500, under=-900)
        conn.commit()

        pairs = clv_repo.load_open_close_pairs(conn)

    assert len(pairs) == 1
    assert pairs[0].open_over == -110          # earliest pre-game
    assert pairs[0].close_over == -140         # latest pre-game, not the in-play one
    assert pairs[0].close_at < TIP


def test_report_scores_the_pair_and_excludes_moved_lines(clean_db):
    with clean_db.connection() as conn:
        game_id, player_id = _seed_game(conn)
        # fanduel: price moves, line holds -> scoreable.
        _insert_prop(conn, game_id, player_id, at=TIP - timedelta(hours=8), over=-110, under=-110)
        _insert_prop(conn, game_id, player_id, at=TIP - timedelta(hours=1), over=120, under=-140)
        # draftkings: line moves -> counted, not scored.
        _insert_prop(conn, game_id, player_id, at=TIP - timedelta(hours=8),
                     over=-110, under=-110, line=8.5, vendor="draftkings")
        _insert_prop(conn, game_id, player_id, at=TIP - timedelta(hours=1),
                     over=-110, under=-110, line=7.5, vendor="draftkings")
        conn.commit()

    report = build_clv_report(clean_db)

    assert report.pairs == 2
    assert report.scored == 1
    assert report.line_moved == 1
    # Under bought at -110, closed at -140: the market came to agree.
    assert report.mean_clv is not None and report.mean_clv > 0


def test_a_single_capture_is_not_a_pair(clean_db):
    """One quote has no movement to measure and must not read as zero CLV."""
    with clean_db.connection() as conn:
        game_id, player_id = _seed_game(conn)
        _insert_prop(conn, game_id, player_id, at=TIP - timedelta(hours=3), over=-110, under=-110)
        conn.commit()

        assert clv_repo.load_open_close_pairs(conn) == ()
