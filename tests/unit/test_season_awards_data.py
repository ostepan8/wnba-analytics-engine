"""Structural sanity checks on the hand-researched SEASON_AWARD_WINNERS
dataset itself (no DB) -- catches copy/paste mistakes in
season_awards_data.py (e.g. a season with only 4 All-WNBA First Team
names, or an accidental duplicate row) that a DB-level test wouldn't
surface directly.
"""

from __future__ import annotations

from collections import Counter

from wnba_engine.pipeline.season_awards_data import SEASON_AWARD_WINNERS

_SEASONS = (2022, 2023, 2024, 2025)
_SPLIT_TEAM_AWARDS = ("all_wnba", "all_defense")
_SINGLE_WINNER_AWARDS = ("mvp", "roy", "sixth_poy", "mip", "coy", "finals_mvp")


def test_no_duplicate_dedup_keys():
    keys = [(w.season, w.award, w.team_selection, w.raw_name) for w in SEASON_AWARD_WINNERS]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    assert duplicates == []


def test_every_row_has_a_non_empty_source():
    assert all(w.source.startswith("http") for w in SEASON_AWARD_WINNERS)


def test_every_row_has_a_non_empty_raw_name():
    assert all(w.raw_name.strip() for w in SEASON_AWARD_WINNERS)


def test_split_team_awards_have_exactly_five_per_team_selection_per_season():
    for season in _SEASONS:
        for award in _SPLIT_TEAM_AWARDS:
            for selection in ("first", "second"):
                names = [
                    w.raw_name
                    for w in SEASON_AWARD_WINNERS
                    if w.season == season and w.award == award and w.team_selection == selection
                ]
                assert len(names) == 5, f"{season} {award} {selection}: {names}"
                assert len(set(names)) == 5, f"{season} {award} {selection} has a duplicate name"


def test_all_rookie_is_a_single_five_player_team_not_split():
    for season in _SEASONS:
        rows = [w for w in SEASON_AWARD_WINNERS if w.season == season and w.award == "all_rookie"]
        assert len(rows) == 5, f"{season} all_rookie: {[r.raw_name for r in rows]}"
        assert all(w.team_selection == "na" for w in rows)


def test_single_winner_awards_present_every_season_except_dpoy_2025_tie():
    for season in _SEASONS:
        for award in _SINGLE_WINNER_AWARDS:
            rows = [w for w in SEASON_AWARD_WINNERS if w.season == season and w.award == award]
            assert len(rows) == 1, f"{season} {award}: expected exactly 1 row, got {rows}"


def test_dpoy_has_two_co_winners_only_in_2025():
    for season in (2022, 2023, 2024):
        rows = [w for w in SEASON_AWARD_WINNERS if w.season == season and w.award == "dpoy"]
        assert len(rows) == 1, f"{season} dpoy: {rows}"

    rows_2025 = [w for w in SEASON_AWARD_WINNERS if w.season == 2025 and w.award == "dpoy"]
    assert {w.raw_name for w in rows_2025} == {"A'ja Wilson", "Alanna Smith"}


def test_coach_of_the_year_rows_carry_a_coach_team_name():
    coy_rows = [w for w in SEASON_AWARD_WINNERS if w.award == "coy"]
    assert len(coy_rows) == 4
    assert all(w.coach_team_name for w in coy_rows)


def test_no_season_2026_included_yet():
    assert all(w.season != 2026 for w in SEASON_AWARD_WINNERS)


def test_no_award_row_incorrectly_carries_a_coach_team_name():
    for w in SEASON_AWARD_WINNERS:
        if w.award != "coy":
            assert w.coach_team_name is None, f"{w.season} {w.award} {w.raw_name}"
