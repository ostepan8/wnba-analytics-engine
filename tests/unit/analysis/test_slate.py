"""Ranking a day's props into the few worth reading first.

The ordering is the whole product here: whatever floats to the top of a slate is
what a reader looks at, so the failure modes that matter are a thin sample being
allowed to headline, a settled price masquerading as an opinion, and a streak
that counts a push as a result.
"""

from __future__ import annotations

from wnba_engine.analysis.slate import (
    MIN_DECIDED_FOR_SLATE,
    PRICE_BAND,
    current_streak,
    gap_balance,
    price_gap,
    rank_slate_trends,
    window,
)


def w(label: str, *, overs: int, unders: int, pushes: int = 0, rate: float | None = None):
    decided = overs + unders
    return {
        "label": label,
        "games": decided + pushes,
        "overs": overs,
        "unders": unders,
        "pushes": pushes,
        "average": None,
        "rate": rate if rate is not None else (overs / decided if decided else None),
    }


def prop(
    *,
    overs: int,
    unders: int,
    price: float | None,
    player_id: int = 7,
    name: str = "A Player",
    recent: list[dict] | None = None,
):
    return {
        "game_id": 1,
        "player_id": player_id,
        "full_name": name,
        "prop_type": "points",
        "line": 15.5,
        "over_probability": price,
        "provider": "kalshi",
        "windows": [w("L5", overs=3, unders=2), w("L10", overs=overs, unders=unders),
                    w("Season", overs=20, unders=10)],
        "recent": recent or [],
    }


def hit(cleared: str, *, game_id: int = 1):
    return {"game_id": game_id, "value": 20, "cleared": cleared}


class TestWindowLookup:
    def test_finds_a_window_by_label(self) -> None:
        found = window([w("L5", overs=1, unders=1), w("L10", overs=6, unders=2)], "L10")
        assert found is not None
        assert found["overs"] == 6

    def test_missing_label_is_none_not_an_error(self) -> None:
        assert window([w("L5", overs=1, unders=1)], "vs opp") is None

    def test_empty_windows_is_none(self) -> None:
        assert window([], "L10") is None


class TestStreak:
    def test_counts_the_run_ending_at_the_most_recent_game(self) -> None:
        streak = current_streak([hit("over"), hit("over"), hit("over"), hit("under")])
        assert streak == {"direction": "over", "length": 3}

    def test_a_push_neither_breaks_nor_extends_a_run(self) -> None:
        """A push is not a result. Treating it as the opposite outcome would end
        streaks that never ended; treating it as a hit would invent them."""
        streak = current_streak([hit("over"), hit("push"), hit("over")])
        assert streak == {"direction": "over", "length": 2}

    def test_no_decided_games_is_none(self) -> None:
        assert current_streak([hit("push")]) is None
        assert current_streak([]) is None

    def test_a_single_game_is_a_streak_of_one(self) -> None:
        assert current_streak([hit("under")]) == {"direction": "under", "length": 1}


class TestPriceGap:
    def test_gap_is_recent_rate_minus_the_price(self) -> None:
        gap = price_gap(prop(overs=8, unders=2, price=0.5))
        assert gap is not None
        assert round(gap, 3) == 0.3

    def test_a_gap_can_be_negative(self) -> None:
        gap = price_gap(prop(overs=2, unders=8, price=0.6))
        assert gap is not None
        assert gap < 0

    def test_no_price_means_no_gap(self) -> None:
        assert price_gap(prop(overs=8, unders=2, price=None)) is None

    def test_a_thin_window_produces_no_gap(self) -> None:
        """Under the slate minimum the rate is not something we would print, and
        a gap measured against it is that same rate wearing a different name."""
        thin = MIN_DECIDED_FOR_SLATE - 1
        assert price_gap(prop(overs=thin, unders=0, price=0.5)) is None


class TestRanking:
    def test_biggest_disagreement_first_in_either_direction(self) -> None:
        small = prop(overs=6, unders=3, price=0.6, player_id=1, name="Small")
        big = prop(overs=1, unders=9, price=0.8, player_id=2, name="Big")
        ranked = rank_slate_trends([small, big])
        assert [row["full_name"] for row in ranked] == ["Big", "Small"]

    def test_thin_and_unpriced_props_do_not_appear(self) -> None:
        rows = rank_slate_trends(
            [
                prop(overs=3, unders=0, price=0.5, player_id=1),
                prop(overs=8, unders=2, price=None, player_id=2),
                prop(overs=8, unders=2, price=0.5, player_id=3, name="Kept"),
            ]
        )
        assert [row["full_name"] for row in rows] == ["Kept"]

    def test_limit_caps_the_list(self) -> None:
        props = [
            prop(overs=9, unders=1, price=0.1 * index, player_id=index)
            for index in range(1, 9)
        ]
        assert len(rank_slate_trends(props, limit=3)) == 3

    def test_each_row_carries_what_it_was_ranked_on(self) -> None:
        """The ordering has to be checkable against what is displayed rather
        than taken on trust."""
        row = rank_slate_trends(
            [prop(overs=8, unders=2, price=0.5, recent=[hit("over"), hit("over")])]
        )[0]
        assert row["l10"]["overs"] == 8
        assert row["l10"]["unders"] == 2
        assert row["season"]["label"] == "Season"
        assert row["streak"] == {"direction": "over", "length": 2}
        assert row["gap"] == 0.3
        assert row["line"] == 15.5
        assert row["provider"] == "kalshi"

    def test_empty_input_is_an_empty_list(self) -> None:
        assert rank_slate_trends([]) == []

    def test_min_decided_is_configurable_for_a_caller_that_wants_more(self) -> None:
        props = [prop(overs=6, unders=1, price=0.2)]
        assert rank_slate_trends(props) != []
        assert rank_slate_trends(props, min_decided=10) == []


class TestExtremePrices:
    """Ranking by the size of a disagreement puts the tails on top, and the
    tails are where the disagreements are fake."""

    def test_a_near_zero_price_is_not_a_disagreement(self) -> None:
        low = PRICE_BAND[0]
        assert rank_slate_trends([prop(overs=6, unders=4, price=low / 2)]) == []
        assert rank_slate_trends([prop(overs=6, unders=4, price=1.0)]) == []

    def test_prices_inside_the_band_still_rank(self) -> None:
        low, high = PRICE_BAND
        assert rank_slate_trends([prop(overs=6, unders=4, price=low)]) != []
        assert rank_slate_trends([prop(overs=6, unders=4, price=high)]) != []


class TestRuledOutPlayers:
    """A hit rate for someone who is not playing is not a claim about tonight,
    and the venues price her over near zero -- so those rows sort straight to
    the top unless they are removed."""

    def test_props_for_a_ruled_out_player_are_dropped(self) -> None:
        rows = rank_slate_trends(
            [
                prop(overs=9, unders=1, price=0.05, player_id=1, name="Scratched"),
                prop(overs=7, unders=3, price=0.5, player_id=2, name="Playing"),
            ],
            unavailable={1},
        )
        assert [row["full_name"] for row in rows] == ["Playing"]

    def test_no_exclusions_keeps_everyone(self) -> None:
        props = [prop(overs=7, unders=3, price=0.5, player_id=2)]
        assert rank_slate_trends(props, unavailable=set()) != []
        assert rank_slate_trends(props, unavailable=None) != []


class TestGapBalance:
    """A top-twelve list where every gap points the same way looks like twelve
    findings and is usually one. Counting the direction over the full set is
    what tells those apart."""

    def test_counts_each_direction_over_every_rankable_prop(self) -> None:
        balance = gap_balance(
            [
                prop(overs=9, unders=1, price=0.4, player_id=1),
                prop(overs=8, unders=2, price=0.4, player_id=2),
                prop(overs=1, unders=9, price=0.6, player_id=3),
            ]
        )
        assert balance["rankable"] == 3
        assert balance["above"] == 2
        assert balance["below"] == 1

    def test_it_counts_the_whole_board_not_just_the_top_few(self) -> None:
        props = [
            prop(overs=9, unders=1, price=0.4, player_id=index) for index in range(20)
        ]
        assert gap_balance(props)["rankable"] == 20
        assert len(rank_slate_trends(props)) == 12

    def test_it_applies_the_same_exclusions_as_the_ranking(self) -> None:
        props = [
            prop(overs=9, unders=1, price=0.4, player_id=1),
            prop(overs=9, unders=1, price=0.001, player_id=2),
            prop(overs=9, unders=1, price=0.4, player_id=3),
        ]
        assert gap_balance(props, unavailable={3})["rankable"] == 1

    def test_median_is_the_middle_of_an_even_set(self) -> None:
        balance = gap_balance(
            [
                prop(overs=6, unders=4, price=0.4, player_id=1),
                prop(overs=8, unders=2, price=0.4, player_id=2),
            ]
        )
        assert balance["median_gap"] == 0.3

    def test_nothing_rankable_is_reported_as_nothing(self) -> None:
        assert gap_balance([]) == {
            "rankable": 0,
            "above": 0,
            "below": 0,
            "median_gap": None,
        }
