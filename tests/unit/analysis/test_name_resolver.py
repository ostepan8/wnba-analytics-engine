"""Choosing which known player a loose name refers to.

The interesting tests are all refusals. A wrong answer here is the failure this
project has already had -- 43% of prop rows once carried the wrong player -- so
what matters is not that a good reply is understood, but that every bad reply
is rejected rather than coerced into a real player id.
"""

from __future__ import annotations

from wnba_engine.llm.name_resolver import (
    Candidate,
    build_prompt,
    candidates_as_json,
    confident_match,
    parse_choice,
    resolve,
)

CANDIDATES = (
    Candidate(player_id=11, full_name="Cheyenne Parker-Tyus", team_abbreviation="LV"),
    Candidate(player_id=22, full_name="Cheyenne Parker", team_abbreviation="ATL"),
    Candidate(player_id=33, full_name="Tyus Jones", team_abbreviation="NY"),
)


def replying(text: str | None):
    return lambda _prompt: text


class TestPrompt:
    def test_candidates_are_numbered_from_one(self) -> None:
        prompt = build_prompt("Parker- Tyus, Cheyenne", CANDIDATES)
        assert "1. Cheyenne Parker-Tyus (LV)" in prompt
        assert "3. Tyus Jones (NY)" in prompt

    def test_the_name_is_quoted_verbatim(self) -> None:
        """Including the extractor's damage — the model is being asked about the
        string we actually have, not a cleaned-up version of it."""
        assert '"Parker- Tyus, Cheyenne"' in build_prompt("Parker- Tyus, Cheyenne", CANDIDATES)

    def test_context_is_included_when_given(self) -> None:
        prompt = build_prompt("Smith", CANDIDATES, context="Las Vegas Aces")
        assert "Las Vegas Aces" in prompt

    def test_declining_is_offered_explicitly(self) -> None:
        """A model forced to choose will always choose something."""
        assert "0" in build_prompt("Nobody", CANDIDATES)


class TestParsing:
    def test_a_bare_number_is_the_choice(self) -> None:
        assert parse_choice("1", 3) == 1

    def test_zero_means_none_of_them(self) -> None:
        assert parse_choice("0", 3) == 0

    def test_a_number_inside_prose_is_still_read(self) -> None:
        assert parse_choice("The answer is 2.", 3) == 2

    def test_an_out_of_range_number_is_no_answer(self) -> None:
        """Answering 9 against a list of three has chosen nobody. Clamping or
        wrapping it onto a real player is how a confident wrong row appears."""
        assert parse_choice("9", 3) is None
        assert parse_choice("-1", 3) is None

    def test_a_non_numeric_reply_is_no_answer(self) -> None:
        assert parse_choice("Cheyenne Parker-Tyus", 3) is None
        assert parse_choice("", 3) is None
        assert parse_choice(None, 3) is None


class TestResolve:
    def test_a_valid_choice_returns_that_candidate(self) -> None:
        result = resolve("Parker- Tyus, Cheyenne", CANDIDATES, replying("1"))
        assert result.player_id == 11

    def test_a_decline_resolves_to_nobody(self) -> None:
        result = resolve("Someone Else", CANDIDATES, replying("0"))
        assert result.player_id is None
        assert result.declined is True

    def test_an_unparseable_reply_resolves_to_nobody(self) -> None:
        result = resolve("Whoever", CANDIDATES, replying("I think it's Cheyenne"))
        assert result.player_id is None
        assert result.declined is False

    def test_the_model_cannot_return_a_player_it_was_not_offered(self) -> None:
        """The reply is an index into the shortlist, so there is no path by
        which an unoffered player id comes back."""
        result = resolve("Whoever", CANDIDATES, replying("2"))
        assert result.player_id in {c.player_id for c in CANDIDATES}

    def test_an_unreachable_model_resolves_to_nobody(self) -> None:
        """Degrading to 'unresolved' is exactly the behaviour the caller had
        before this existed; a scheduled ingest must not fail because a box is
        asleep."""

        def explode(_prompt: str) -> str:
            raise RuntimeError("connection refused")

        result = resolve("Whoever", CANDIDATES, explode)
        assert result.player_id is None
        assert result.raw_reply is None

    def test_no_candidates_means_no_question_is_asked(self) -> None:
        asked = []

        def record(prompt: str) -> str:
            asked.append(prompt)
            return "1"

        result = resolve("Whoever", (), record)
        assert result.player_id is None
        assert asked == []

    def test_the_shortlist_is_capped(self) -> None:
        many = tuple(Candidate(player_id=index, full_name=f"Player {index}") for index in range(50))
        result = resolve("Player", many, replying("0"), max_candidates=5)
        assert len(result.candidates) == 5

    def test_an_index_past_the_cap_is_rejected(self) -> None:
        """The cap shortens the list, so a reply valid for the full list must
        not be valid for the trimmed one."""
        many = tuple(Candidate(player_id=index, full_name=f"Player {index}") for index in range(50))
        result = resolve("Player", many, replying("9"), max_candidates=5)
        assert result.player_id is None


class TestAuditTrail:
    def test_candidates_are_recorded_for_later_review(self) -> None:
        """A bad call has to be re-examinable against what was on the table."""
        assert candidates_as_json(CANDIDATES)[0] == {
            "player_id": 11,
            "full_name": "Cheyenne Parker-Tyus",
            "team": "LV",
            "score": None,
        }


class TestConfidentMatch:
    """A trigram match that is obviously right should never reach the model --
    it is slower, costlier and less certain than the arithmetic already done."""

    def test_a_clear_leader_is_taken_without_asking(self) -> None:
        best = confident_match(
            [
                Candidate(player_id=11, full_name="Cheyenne Parker-Tyus", score=1.0),
                Candidate(player_id=22, full_name="Cheyenne Parker", score=0.55),
            ]
        )
        assert best is not None and best.player_id == 11

    def test_two_close_candidates_are_a_judgement_call(self) -> None:
        """0.82 against 0.80 is exactly the ambiguity the model exists for."""
        assert (
            confident_match(
                [
                    Candidate(player_id=11, full_name="A Smith", score=0.82),
                    Candidate(player_id=22, full_name="B Smith", score=0.80),
                ]
            )
            is None
        )

    def test_a_weak_leader_is_not_confident(self) -> None:
        assert confident_match([Candidate(player_id=11, full_name="Someone", score=0.4)]) is None

    def test_unscored_candidates_are_never_confident(self) -> None:
        assert confident_match([Candidate(player_id=11, full_name="Someone")]) is None

    def test_no_candidates_is_no_match(self) -> None:
        assert confident_match([]) is None
