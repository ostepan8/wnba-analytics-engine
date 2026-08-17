"""What a team is missing, in minutes and production.

The bucketing carries the whole claim. Counting a questionable starter as gone
overstates the absence; counting a doubtful one as present understates it; and
treating an unrecognised status as "out" invents an absence from a word we did
not understand.
"""

from __future__ import annotations

from wnba_engine.analysis.availability import (
    bucket,
    share_of,
    summarise_absences,
)


def player(name: str, status: str, *, minutes=0.0, points=0.0, rebounds=0.0, assists=0.0):
    return {
        "full_name": name,
        "status": status,
        "minutes": minutes,
        "points": points,
        "rebounds": rebounds,
        "assists": assists,
    }


class TestBucketing:
    def test_out_and_doubtful_both_count_as_gone(self) -> None:
        """Doubtful is the league's word for unlikely, not for a coin flip."""
        assert bucket("Out") == "out"
        assert bucket("Doubtful") == "out"

    def test_questionable_and_day_to_day_are_undecided(self) -> None:
        assert bucket("Questionable") == "at_risk"
        assert bucket("Day-To-Day") == "at_risk"

    def test_probable_is_expected_to_play(self) -> None:
        assert bucket("Probable") == "likely"
        assert bucket("Available") == "likely"

    def test_matching_ignores_case_and_padding(self) -> None:
        assert bucket("  qUeStIoNaBlE ") == "at_risk"

    def test_an_unknown_status_is_none_not_out(self) -> None:
        """A status we do not understand is not evidence anyone is missing;
        defaulting it into `out` would overstate every total below it."""
        assert bucket("Suspended") is None
        assert bucket(None) is None
        assert bucket("") is None


class TestSummary:
    def test_production_is_totalled_per_bucket(self) -> None:
        summary = summarise_absences(
            [
                player("Star", "Out", minutes=34.0, points=21.0, rebounds=8.0, assists=5.0),
                player("Bench", "Out", minutes=6.0, points=2.0),
                player("Maybe", "Questionable", minutes=30.0, points=15.0),
                player("Fine", "Probable", minutes=28.0, points=12.0),
            ]
        )
        assert summary["out"]["minutes"] == 40.0
        assert summary["out"]["points"] == 23.0
        assert summary["out"]["count"] == 2
        assert summary["at_risk"]["points"] == 15.0
        assert summary["likely"]["points"] == 12.0

    def test_the_biggest_absence_is_listed_first(self) -> None:
        """Whoever moves a total most should be the first name read."""
        summary = summarise_absences(
            [
                player("Bench", "Out", minutes=6.0),
                player("Star", "Out", minutes=34.0),
            ]
        )
        assert [row["full_name"] for row in summary["out"]["players"]] == ["Star", "Bench"]

    def test_a_player_with_no_games_contributes_nothing_but_is_still_listed(self) -> None:
        """A signing who has not debuted is on the report and is not missing
        production."""
        summary = summarise_absences([{"full_name": "New", "status": "Out", "minutes": None}])
        assert summary["out"]["count"] == 1
        assert summary["out"]["minutes"] == 0.0

    def test_unknown_statuses_land_in_no_bucket(self) -> None:
        summary = summarise_absences([player("Odd", "Suspended", minutes=30.0)])
        assert all(summary[name]["count"] == 0 for name in ("out", "at_risk", "likely"))

    def test_every_bucket_exists_even_when_empty(self) -> None:
        """The UI reads these unconditionally; a missing key would be a crash
        on the happy path of a fully healthy team."""
        summary = summarise_absences([])
        assert summary["out"] == {
            "players": [],
            "count": 0,
            "minutes": 0.0,
            "points": 0.0,
            "rebounds": 0.0,
            "assists": 0.0,
        }


class TestShare:
    def test_share_is_a_fraction_of_the_team_total(self) -> None:
        assert share_of(23.0, 82.0) == 0.28

    def test_no_denominator_is_none_not_zero(self) -> None:
        """"0% of the scoring is missing" is a claim we would not have earned."""
        assert share_of(23.0, None) is None
        assert share_of(23.0, 0) is None

    def test_nothing_missing_is_zero(self) -> None:
        assert share_of(0.0, 82.0) == 0.0
