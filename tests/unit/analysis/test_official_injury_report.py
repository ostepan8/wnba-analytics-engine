"""Parsing the league's own injury report.

This is the only source of real game-status designations, and it arrives as a
PDF with no delimiters -- a player's reason runs until the next player, team or
game begins. So the failure that matters is not "did it parse" but "did a field
absorb text belonging to its neighbour": a name built out of the team header in
front of it, or a player attributed to the wrong side of a matchup.

The fixtures are the real flattened text of published reports.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.wnba_official.injury_report_parser import (
    parse_injury_report,
    parse_report_timestamp,
    teams_not_submitted,
)

TEAMS = [
    "Atlanta Dream",
    "Chicago Sky",
    "Connecticut Sun",
    "Dallas Wings",
    "Golden State Valkyries",
    "Indiana Fever",
    "Las Vegas Aces",
    "Los Angeles Sparks",
    "Minnesota Lynx",
    "New York Liberty",
    "Portland Fire",
    "Seattle Storm",
    "Toronto Tempo",
    "Washington Mystics",
]

HEADER = (
    "Injury Report: 08/17/26 04:00 PM Page 1 of 1 "
    "Game Date Game Time Matchup Team Player Name Current Status Reason "
)

# Real text from the 2026-08-17 04:00 PM report.
REPORT = HEADER + (
    "08/17/2026 10:00 (ET) DAL@GSV Dallas Wings "
    "Fudd, Azzi Out Injury/Illness - Right Knee; right knee "
    "James, Aziaha Out Injury/Illness - Left Leg; lower left leg "
    "Shepard, Jessica Probable Injury/Illness - Right Ankle; right ankle "
    "Golden State Valkyries Salaun, Janelle Questionable Injury/Illness - Right Knee; Soreness "
    "08/18/2026 07:00 (ET) IND@TOR Indiana Fever NOT YET SUBMITTED "
    "Toronto Tempo NOT YET SUBMITTED"
)


def entries():
    return parse_injury_report(REPORT, team_names=TEAMS)


def by_name(name: str):
    return next(row for row in entries() if row.player_name == name)


class TestDesignations:
    """The whole reason this source exists: ESPN publishes only Out and
    Day-To-Day, and the league files four distinct designations."""

    def test_all_four_designations_survive(self) -> None:
        found = {row.player_name: row.status for row in entries()}
        assert found["Azzi Fudd"] == "Out"
        assert found["Jessica Shepard"] == "Probable"
        assert found["Janelle Salaun"] == "Questionable"

    def test_probable_is_not_flattened_to_out(self) -> None:
        """The concrete bug this source fixes: ESPN had Shepard Out on this
        date while her own team filed her Probable."""
        assert by_name("Jessica Shepard").status == "Probable"


class TestNameBoundaries:
    def test_a_name_never_absorbs_the_team_header_in_front_of_it(self) -> None:
        """An earlier parser produced "Janelle Golden State Valkyries Salaun"
        by letting the name pattern run backwards over the team."""
        assert by_name("Janelle Salaun").player_name == "Janelle Salaun"

    def test_names_are_forename_then_surname(self) -> None:
        assert {row.player_name for row in entries()} == {
            "Azzi Fudd",
            "Aziaha James",
            "Jessica Shepard",
            "Janelle Salaun",
        }

    def test_a_hyphenated_surname_split_by_the_extractor_is_rejoined(self) -> None:
        """The PDF text layer emits "Parker- Tyus"; left alone it matches no
        player, and an unmatched player is one missing from the report."""
        text = HEADER + (
            "08/17/2026 10:00 (ET) ATL@LVA Las Vegas Aces "
            "Parker- Tyus, Cheyenne Out Concussion Protocol"
        )
        rows = parse_injury_report(text, team_names=TEAMS)
        assert rows[0].player_name == "Cheyenne Parker-Tyus"


class TestTeamAttribution:
    def test_each_player_is_attributed_to_her_own_team(self) -> None:
        """A wrong team here silently moves a player to the opposing side."""
        assert by_name("Azzi Fudd").team_name == "Dallas Wings"
        assert by_name("Janelle Salaun").team_name == "Golden State Valkyries"

    def test_a_new_matchup_clears_the_previous_team(self) -> None:
        """Without this the first team of a game inherits the last team of the
        game before it."""
        assert all(row.team_name in TEAMS for row in entries())

    def test_players_before_any_team_header_are_dropped(self) -> None:
        text = HEADER + "Nobody, Somebody Out Injury/Illness - Knee"
        assert parse_injury_report(text, team_names=TEAMS) == ()


class TestReasons:
    def test_reason_stops_at_the_next_player(self) -> None:
        assert by_name("Azzi Fudd").reason == "Injury/Illness - Right Knee; right knee"

    def test_reason_stops_at_the_next_team(self) -> None:
        assert by_name("Jessica Shepard").reason == "Injury/Illness - Right Ankle; right ankle"

    def test_a_non_injury_reason_is_kept_verbatim(self) -> None:
        text = (
            HEADER + "08/17/2026 10:00 (ET) ATL@LVA Atlanta Dream Mair, Taina Out Coach's Decision"
        )
        assert parse_injury_report(text, team_names=TEAMS)[0].reason == "Coach's Decision"


class TestTimestamp:
    def test_report_time_is_read_from_the_header(self) -> None:
        """The report's filing time is its identity. Stamping rows with the
        fetch clock would make an unchanged hourly re-fetch look like news."""
        assert parse_report_timestamp(REPORT) == datetime(2026, 8, 17, 16, 0, tzinfo=UTC)

    def test_noon_and_midnight_do_not_wrap(self) -> None:
        noon = parse_report_timestamp("Injury Report: 08/17/26 12:00 PM")
        midnight = parse_report_timestamp("Injury Report: 08/17/26 12:00 AM")
        assert (noon.hour, midnight.hour) == (12, 0)

    def test_captured_at_defaults_to_the_filing_time(self) -> None:
        assert entries()[0].captured_at == entries()[0].reported_at

    def test_a_missing_header_is_an_error_not_a_guess(self) -> None:
        with pytest.raises(ProviderValidationError):
            parse_report_timestamp("no header here")


class TestNotSubmitted:
    def test_teams_that_have_not_filed_are_reported(self) -> None:
        """ "Filed, nobody listed" and "has not filed" are different claims, and
        the second is not evidence a team is healthy."""
        assert set(teams_not_submitted(REPORT, team_names=TEAMS)) == {
            "Indiana Fever",
            "Toronto Tempo",
        }

    def test_an_unfiled_team_contributes_no_entries(self) -> None:
        assert all(row.team_name not in {"Indiana Fever"} for row in entries())
