"""Unit tests for the stats.wnba.com parsers.

Fixtures mirror real payloads captured on 2026-08-04 (LeagueID=10).
"""

from __future__ import annotations

from datetime import date

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.wnba_stats import parser
from wnba_engine.wnba_stats.team_matching import parse_matchup, to_canonical


def _result_set(name: str, headers: list[str], rows: list[list]) -> dict:
    return {"resultSets": [{"name": name, "headers": headers, "rowSet": rows}]}


PBP_HEADERS = [
    "GAME_ID", "EVENTNUM", "EVENTMSGTYPE", "EVENTMSGACTIONTYPE", "PERIOD",
    "PCTIMESTRING", "HOMEDESCRIPTION", "NEUTRALDESCRIPTION", "VISITORDESCRIPTION",
    "SCORE", "PERSON1TYPE", "PLAYER1_ID", "PLAYER1_NAME", "PLAYER1_TEAM_ID",
    "PERSON2TYPE", "PLAYER2_ID", "PLAYER2_NAME",
    "PERSON3TYPE", "PLAYER3_ID", "PLAYER3_NAME",
]


def test_a_team_rebound_does_not_become_a_player() -> None:
    """THE trap in this feed.

    PERSON1TYPE 2 and 3 mean the slot holds a TEAM, and PLAYER1_ID then
    carries a team id (1611661xxx) with a null name -- team rebounds,
    timeouts, delay of game. Reading the id without checking the type
    attributed 8% of events to a "player" that is a franchise: 27 of 341 in
    the first game examined.
    """
    payload = _result_set(
        "PlayByPlay", PBP_HEADERS,
        [["1022500003", 17, 4, 0, 1, "8:42", "VALKYRIES Rebound", None, None, None,
          2, 1611661331, None, None, 0, 0, None, 0, 0, None]],
    )
    (play,) = parser.parse_play_by_play(payload)
    assert play.player1_external_id is None
    assert play.player1_name is None
    # The team is still captured -- it just is not a player.
    assert play.team_external_id == "1611661331"


def test_a_real_player_event_keeps_all_three_slots() -> None:
    """Slots are not interchangeable: 1 acts, 2 is the secondary participant
    (assister on a make, shooter on a block), 3 a third party. Flattening
    them loses the relationship that makes this source worth adding.
    """
    payload = _result_set(
        "PlayByPlay", PBP_HEADERS,
        [["1022500003", 45, 1, 1, 1, "9:55", "Plum 2' Layup (Stevens 1 AST)",
          None, None, "2 - 0",
          5, 1628276, "Kelsey Plum", 1611661320,
          4, 1627701, "Azura Stevens", 0, 0, None]],
    )
    (play,) = parser.parse_play_by_play(payload)
    assert play.player1_external_id == "1628276"
    assert play.player2_external_id == "1627701"
    assert play.player2_name == "Azura Stevens"
    assert play.player3_external_id is None
    assert play.score == "2 - 0"


def test_a_zero_id_is_absent_not_a_player_numbered_zero() -> None:
    """The feed uses 0 for an empty slot rather than null."""
    payload = _result_set(
        "PlayByPlay", PBP_HEADERS,
        [["1022500003", 2, 12, 0, 1, "10:00", "Start of 1st Period", None, None, None,
          0, 0, None, None, 0, 0, None, 0, 0, None]],
    )
    (play,) = parser.parse_play_by_play(payload)
    assert play.player1_external_id is None


def test_event_labels_never_return_null() -> None:
    """game_plays.play_type is NOT NULL, and an unmapped code is more useful
    rendered than rejected -- the row still carries its description and
    numeric type.
    """
    assert parser.event_label(1) == "Made Shot"
    assert parser.event_label(12) == "Period Begin"
    assert parser.event_label(99) == "Event 99"
    assert parser.event_label(None) == "Unknown"


def test_shot_chart_carries_coordinates_and_clock() -> None:
    payload = _result_set(
        "Shot_Chart_Detail",
        ["GAME_ID", "GAME_EVENT_ID", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "PERIOD",
         "MINUTES_REMAINING", "SECONDS_REMAINING", "ACTION_TYPE", "SHOT_TYPE",
         "SHOT_ZONE_BASIC", "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE", "SHOT_DISTANCE",
         "LOC_X", "LOC_Y", "SHOT_MADE_FLAG"],
        [["1022500003", 45, 1628276, "Kelsey Plum", 1611661320, 1, 9, 55,
          "Driving Layup Shot", "2PT Field Goal", "Restricted Area", "Center(C)",
          "Less Than 8 ft.", 2, -20, 1, 0]],
    )
    (shot,) = parser.parse_shot_chart(payload)
    assert shot.loc_x == -20 and shot.loc_y == 1
    assert shot.seconds_remaining == 9 * 60 + 55
    assert shot.made is False
    assert shot.player_external_id == "1628276"


def test_game_log_reads_home_from_the_matchup_separator() -> None:
    """'A vs. B' is A at home; 'A @ B' is A away. Order alone does not say."""
    payload = _result_set(
        "LeagueGameLog",
        ["GAME_ID", "GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP"],
        [["1022500283", "2025-09-11", "CHI", "CHI vs. NYL"],
         ["1022500283", "2025-09-11", "NYL", "NYL @ CHI"]],
    )
    home, away = parser.parse_game_log(payload, season=2025)
    assert home.game_date == date(2025, 9, 11)
    assert home.is_home is True
    assert away.is_home is False


def test_abbreviations_are_mapped_not_guessed() -> None:
    """Five of thirteen disagree with ours and the difference is not
    derivable (GSV drops a letter, WAS moves one). An unknown abbreviation
    passes through so it fails to find a team rather than finding a wrong
    one.
    """
    assert to_canonical("GSV") == "GS"
    assert to_canonical("WAS") == "WSH"
    assert to_canonical("ATL") == "ATL"
    assert to_canonical("ZZZ") == "ZZZ"
    assert parse_matchup("CHI vs. NYL") == ("CHI", "NY")
    assert parse_matchup("NYL @ CHI") == ("CHI", "NY")
    assert parse_matchup("nonsense") is None


def test_a_payload_without_result_sets_is_rejected() -> None:
    with pytest.raises(ProviderValidationError):
        parser.parse_play_by_play({"foo": "bar"})
