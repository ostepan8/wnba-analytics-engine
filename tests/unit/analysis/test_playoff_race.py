"""Clinching arithmetic.

The rule this encodes is league-wide seeding: the WNBA takes the top eight
records regardless of conference, and the provider's playoff_seed is a
CONFERENCE seed that would rank an eleventh-place team fifth if passed through.

Tiebreakers are deliberately not modelled; the tests below pin what IS
knowable — a team that cannot be caught and a team that cannot catch up.
"""

from __future__ import annotations

from wnba_engine.analysis.playoff_race import PLAYOFF_SPOTS, rank_teams


def team(team_id: int, wins: int, losses: int, remaining: int = 0) -> dict[str, object]:
    return {"team_id": team_id, "wins": wins, "losses": losses, "games_remaining": remaining}


def league(*records: tuple[int, int, int, int]) -> list[dict[str, object]]:
    return [team(tid, w, losses, rem) for tid, w, losses, rem in records]


def by_id(ranked: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    return {int(row["team_id"]): row for row in ranked}


class TestSeeding:
    def test_seeds_run_league_wide_not_by_conference(self) -> None:
        """The 2026 shape that motivated this: Chicago is the East's 5-seed and
        eleventh in the league. Only the second number decides a berth."""
        ranked = rank_teams(
            league(
                (1, 29, 7, 8), (2, 24, 9, 11), (3, 24, 12, 8), (4, 22, 12, 10),
                (5, 21, 12, 11), (6, 22, 14, 8), (7, 20, 14, 10), (8, 20, 15, 9),
                (9, 14, 20, 10), (10, 13, 22, 9), (11, 12, 22, 10), (12, 12, 22, 10),
            )
        )
        assert [row["team_id"] for row in ranked][:3] == [1, 2, 3]
        assert by_id(ranked)[11]["seed"] == 11
        assert by_id(ranked)[11]["in_playoff_position"] is False
        assert by_id(ranked)[8]["in_playoff_position"] is True

    def test_ordering_is_by_win_percentage_not_win_count(self) -> None:
        """22-14 (.611) sits behind 21-12 (.636) despite one more win."""
        ranked = rank_teams(league((1, 21, 12, 0), (2, 22, 14, 0)))
        assert [row["team_id"] for row in ranked] == [1, 2]

    def test_a_team_with_no_games_played_sorts_last_rather_than_crashing(self) -> None:
        ranked = rank_teams(league((1, 10, 5, 0), (2, 0, 0, 40)))
        assert [row["team_id"] for row in ranked] == [1, 2]


class TestClinching:
    def test_a_team_nobody_can_catch_has_clinched(self) -> None:
        """One team far clear, everyone else out of reach even winning out."""
        ranked = rank_teams(
            league((1, 30, 0, 0), *[(i, 5, 25, 2) for i in range(2, 12)])
        )
        assert by_id(ranked)[1]["clinched"] is True
        assert by_id(ranked)[1]["magic_number"] is None

    def test_a_team_that_cannot_reach_the_cut_is_eliminated(self) -> None:
        """Its best possible finish is below eight teams' CURRENT records."""
        ranked = rank_teams(
            league(*[(i, 25, 5, 0) for i in range(1, 10)], (99, 2, 30, 1))
        )
        assert by_id(ranked)[99]["eliminated"] is True
        assert by_id(ranked)[99]["in_playoff_position"] is False

    def test_a_contender_is_neither_clinched_nor_eliminated(self) -> None:
        ranked = rank_teams(league(*[(i, 15, 15, 10) for i in range(1, 13)]))
        for row in ranked:
            assert row["clinched"] is False
            assert row["eliminated"] is False

    def test_clinching_needs_fewer_than_eight_teams_able_to_pass(self) -> None:
        """Exactly at the boundary: with PLAYOFF_SPOTS rivals still able to
        finish above it, a team is not yet safe."""
        contenders = [(i, 20, 10, 5) for i in range(2, 2 + PLAYOFF_SPOTS)]
        ranked = rank_teams(league((1, 22, 8, 0), *contenders))
        assert by_id(ranked)[1]["clinched"] is False

    def test_one_fewer_rival_flips_it_to_clinched(self) -> None:
        contenders = [(i, 20, 10, 5) for i in range(2, 1 + PLAYOFF_SPOTS)]
        ranked = rank_teams(league((1, 22, 8, 0), *contenders))
        assert by_id(ranked)[1]["clinched"] is True

    def test_a_finished_season_leaves_nobody_undecided(self) -> None:
        """With no games left every team is either in or out -- never 'still
        playing for it', which would render as a live race in the off-season."""
        ranked = rank_teams(league(*[(i, 30 - i, i, 0) for i in range(1, 13)]))
        for row in ranked:
            assert row["clinched"] or row["eliminated"]


class TestMagicNumber:
    def test_it_counts_wins_still_needed(self) -> None:
        ranked = rank_teams(
            league((1, 20, 10, 6), *[(i, 18, 12, 6) for i in range(2, 12)])
        )
        magic = by_id(ranked)[1]["magic_number"]
        assert isinstance(magic, int) and magic > 0

    def test_it_is_absent_once_settled(self) -> None:
        ranked = rank_teams(league((1, 30, 0, 0), *[(i, 5, 25, 0) for i in range(2, 12)]))
        assert by_id(ranked)[1]["magic_number"] is None
        assert by_id(ranked)[5]["magic_number"] is None

    def test_it_is_absent_when_more_wins_are_needed_than_games_remain(self) -> None:
        """Not yet mathematically eliminated, but it cannot get there on its own
        results. Reporting a number it cannot reach would be worse than none."""
        ranked = rank_teams(
            league(*[(i, 25, 5, 5) for i in range(1, 9)], (99, 4, 26, 2))
        )
        assert by_id(ranked)[99]["magic_number"] is None


class TestGamesBehind:
    def test_it_is_measured_league_wide_not_within_a_conference(self) -> None:
        """The provider reports GB inside a conference, so a fourth-placed team
        that leads its own conference shows 0 — which in a league-wide table
        says it is tied for first."""
        ranked = rank_teams(
            league((1, 29, 7, 0), (2, 24, 9, 0), (3, 24, 12, 0), (4, 22, 12, 0))
        )
        behind = {int(r["team_id"]): r["games_behind_leader"] for r in ranked}
        assert behind[1] == 0
        # 29-7 vs 22-12: (29-22 + 12-7) / 2 = 6
        assert behind[4] == 6

    def test_the_leader_is_zero_behind_itself(self) -> None:
        ranked = rank_teams(league((1, 10, 2, 0), (2, 5, 7, 0)))
        assert ranked[0]["games_behind_leader"] == 0

    def test_teams_above_the_cut_are_never_behind_the_cut(self) -> None:
        """games_behind_playoff is the chase number; a team holding a place is
        clamped to zero rather than reported as negative."""
        ranked = rank_teams(league(*[(i, 20 - i, i, 0) for i in range(1, 13)]))
        for row in ranked[:PLAYOFF_SPOTS]:
            assert row["games_behind_playoff"] == 0
        assert ranked[PLAYOFF_SPOTS]["games_behind_playoff"] > 0


class TestPositionIsNotStatus:
    """The distinction the standings table lives or dies on.

    Sitting below the cut line is not elimination, and sitting above it is not a
    berth. Conflating either one turns a standings page into misinformation.
    """

    def test_a_team_below_the_cut_with_games_left_is_not_eliminated(self) -> None:
        ranked = rank_teams(
            league(*[(i, 20, 10, 8) for i in range(1, 9)], (99, 14, 16, 12))
        )
        chaser = by_id(ranked)[99]
        assert chaser["in_playoff_position"] is False
        assert chaser["eliminated"] is False

    def test_a_team_inside_the_cut_can_still_be_unsettled(self) -> None:
        ranked = rank_teams(league(*[(i, 15, 15, 12) for i in range(1, 13)]))
        leader = ranked[0]
        assert leader["in_playoff_position"] is True
        assert leader["clinched"] is False

    def test_both_sides_of_the_cut_can_be_undecided_at_once(self) -> None:
        """Mid-season, nothing is settled either way — the table must be able to
        say that rather than splitting the league in two."""
        ranked = rank_teams(league(*[(i, 10, 10, 20) for i in range(1, 13)]))
        assert all(not row["clinched"] and not row["eliminated"] for row in ranked)
        assert any(row["in_playoff_position"] for row in ranked)
        assert any(not row["in_playoff_position"] for row in ranked)

    def test_elimination_needs_rivals_beyond_reach_not_merely_ahead(self) -> None:
        """Eight teams are ahead right now, but every one is still catchable, so
        the ninth-placed team is emphatically not out."""
        ranked = rank_teams(
            league(*[(i, 16, 14, 10) for i in range(1, 9)], (99, 15, 15, 10))
        )
        assert by_id(ranked)[99]["eliminated"] is False
