"""Unit tests for the ESPN scoreboard parser (pure, fixture-driven)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.espn.parser import parse_scoreboard
from wnba_engine.models.games import GameStatus


def test_parses_all_events(espn_scoreboard_payload):
    games = parse_scoreboard(espn_scoreboard_payload)
    assert len(games) == 2
    assert [g.external_id for g in games] == ["401736228", "401736227"]


def test_parses_teams_scores_and_status(espn_scoreboard_payload):
    game = parse_scoreboard(espn_scoreboard_payload)[0]
    assert game.status is GameStatus.FINAL
    assert game.is_final
    assert game.season == 2025
    assert game.start_time == datetime(2025, 7, 6, 17, 0, tzinfo=UTC)
    assert game.home_team.external_id == "9"
    assert game.home_team.abbreviation == "NY"
    assert game.home_team.name == "New York Liberty"
    assert game.away_team.external_id == "14"
    assert game.away_team.abbreviation == "SEA"
    assert game.home_score == 70
    assert game.away_score == 79


def test_empty_scoreboard_returns_no_games():
    assert parse_scoreboard({"events": []}) == ()


def test_missing_events_key_raises():
    with pytest.raises(ProviderValidationError, match="events"):
        parse_scoreboard({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_scoreboard(["not", "a", "dict"])


def test_missing_competitors_raises(espn_scoreboard_payload):
    broken = copy.deepcopy(espn_scoreboard_payload)
    del broken["events"][0]["competitions"][0]["competitors"]
    with pytest.raises(ProviderValidationError, match="competitors"):
        parse_scoreboard(broken)


def test_wrong_competitor_count_raises(espn_scoreboard_payload):
    broken = copy.deepcopy(espn_scoreboard_payload)
    broken["events"][0]["competitions"][0]["competitors"].pop()
    with pytest.raises(ProviderValidationError, match="exactly 2 competitors"):
        parse_scoreboard(broken)


def test_scheduled_game_has_no_scores(espn_scoreboard_payload):
    payload = copy.deepcopy(espn_scoreboard_payload)
    event = payload["events"][0]
    event["status"]["type"]["name"] = "STATUS_SCHEDULED"
    for competitor in event["competitions"][0]["competitors"]:
        competitor["score"] = None
    game = parse_scoreboard(payload)[0]
    assert game.status is GameStatus.SCHEDULED
    assert game.home_score is None
    assert game.away_score is None


def test_malformed_score_raises(espn_scoreboard_payload):
    broken = copy.deepcopy(espn_scoreboard_payload)
    broken["events"][0]["competitions"][0]["competitors"][0]["score"] = "seventy"
    with pytest.raises(ProviderValidationError, match="integer"):
        parse_scoreboard(broken)
