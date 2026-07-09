"""Unit tests for the ESPN scoreboard parser (pure, fixture-driven)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.espn.parser import parse_scoreboard
from wnba_engine.models.games import GameStatus, SeasonType


def test_parses_all_events(espn_scoreboard_payload):
    games = parse_scoreboard(espn_scoreboard_payload)
    assert len(games) == 2
    assert [g.external_id for g in games] == ["401736228", "401736227"]


def test_parses_teams_scores_and_status(espn_scoreboard_payload):
    game = parse_scoreboard(espn_scoreboard_payload)[0]
    assert game.status is GameStatus.FINAL
    assert game.is_final
    assert game.season == 2025
    assert game.season_type is SeasonType.REGULAR_SEASON
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


@pytest.mark.parametrize(
    ("season_type_value", "expected"),
    [
        (1, SeasonType.PRESEASON),
        (2, SeasonType.REGULAR_SEASON),
        (3, SeasonType.POSTSEASON),
        (99, SeasonType.OTHER),  # an unrecognized future value must not crash
    ],
)
def test_season_type_distinguishes_preseason_from_regular_season(
    espn_scoreboard_payload, season_type_value, expected
):
    """Regression test: a preseason win previously counted identically to a
    real regular-season win (real bug, caught via a standings mismatch)."""
    payload = copy.deepcopy(espn_scoreboard_payload)
    payload["events"][0]["season"]["type"] = season_type_value
    game = parse_scoreboard(payload)[0]
    assert game.season_type is expected


def test_missing_season_type_raises(espn_scoreboard_payload):
    broken = copy.deepcopy(espn_scoreboard_payload)
    del broken["events"][0]["season"]["type"]
    with pytest.raises(ProviderValidationError, match="'type'"):
        parse_scoreboard(broken)


def test_all_star_game_is_not_regular_season(espn_scoreboard_allstar_payload):
    """Regression test: ESPN sends season.type=2 (regular-season) for the
    All-Star game even though its rosters ("Team Clark", "Team Collier")
    are captain-picked exhibition squads, not real franchises. This
    previously let 4 All-Star games (2022-2025) get ingested as
    regular-season, inflating team records. competitions[0].type is
    ALLSTAR for this game (STD for every normal game), which is the signal
    used to override season.type. Real trimmed ESPN payload, event
    401781604 (2025 All-Star Game, Team Collier @ Team Clark)."""
    game = parse_scoreboard(espn_scoreboard_allstar_payload)[0]
    assert game.season_type is SeasonType.OTHER


def test_non_standard_competition_type_missing_is_treated_as_standard(
    espn_scoreboard_payload,
):
    """A competition with no `type` field at all (older trimmed fixtures,
    or a shape ESPN hasn't sent yet) must fail open and keep the season.type
    -derived classification rather than being misread as non-standard."""
    game = parse_scoreboard(espn_scoreboard_payload)[0]
    assert game.season_type is SeasonType.REGULAR_SEASON


def test_standard_competition_type_does_not_override_season_type(
    espn_scoreboard_payload,
):
    payload = copy.deepcopy(espn_scoreboard_payload)
    payload["events"][0]["competitions"][0]["type"] = {"id": "1", "abbreviation": "STD"}
    game = parse_scoreboard(payload)[0]
    assert game.season_type is SeasonType.REGULAR_SEASON
