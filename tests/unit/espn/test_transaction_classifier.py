"""Unit tests for the best-effort transaction-type/player-name extraction.

Every description string below is real text observed live in ESPN's
transactions feed across the 2022-2025 seasons (see the module docstring
in transaction_classifier.py for the documented, accepted limitations
these tests also encode -- e.g. only the first player/action in a
multi-action description is ever captured).
"""

from __future__ import annotations

from wnba_engine.espn.transaction_classifier import (
    classify_transaction_type,
    extract_raw_player_name,
)

# --- classify_transaction_type -------------------------------------------


def test_classifies_waived():
    assert classify_transaction_type("Waived F Liatu King.") == "waived"


def test_classifies_signed():
    assert classify_transaction_type("Signed G Maya Caldwell to a rest-of-season contract.") == (
        "signed"
    )


def test_classifies_re_signed():
    assert (
        classify_transaction_type("Re-signed G Lindsay Allen to a third seven-day contract.")
        == "re-signed"
    )


def test_classifies_re_signed_espn_typo_variant():
    # Real ESPN typo: "Re-singed" instead of "Re-signed".
    assert (
        classify_transaction_type("Re-singed F Nikolina Milic to a second seven-day contract.")
        == "re-signed"
    )


def test_classifies_released():
    assert classify_transaction_type("Released G Christyn Williams.") == "released"


def test_classifies_activated():
    assert classify_transaction_type("Activated C Kamilla Cardoso.") == "activated"


def test_multi_action_waived_outranks_activated_in_priority_order():
    # Same documented "one type per description" limitation as
    # test_multi_action_description_picks_first_matching_priority_keyword
    # below -- "waived" is a higher-priority keyword than "activated".
    assert classify_transaction_type("Activated F Dorka Juhasz. Waived F Taylor Soule.") == "waived"


def test_classifies_reinstated_as_activated():
    assert classify_transaction_type("Reinstated C Sylvia Fowles.") == "activated"


def test_classifies_claimed():
    assert (
        classify_transaction_type("Claimed G Evina Westrook off waivers from Washington.")
        == "claimed"
    )


def test_classifies_awarded_off_waivers_as_claimed():
    assert (
        classify_transaction_type("Awarded C Iliana Rupert off waivers from Las Vegas.")
        == "claimed"
    )


def test_classifies_traded():
    assert (
        classify_transaction_type(
            "Acquired G Allisha Gray from Dallas in exchange for a 2023 first-round draft pick."
        )
        == "traded"
    )


def test_classifies_placed_on_il():
    assert (
        classify_transaction_type("Placed F Stephanie Talbot on the full season injury list.")
        == "placed_on_il"
    )


def test_placed_without_injury_list_is_not_placed_on_il():
    # "Placed ... on the suspended list" is NOT an injury placement --
    # the classifier must not over-fire on the bare word "placed".
    assert classify_transaction_type("Placed C Luisa Geiselsoder on the suspended list.") != (
        "placed_on_il"
    )


def test_classifies_front_office_named():
    assert classify_transaction_type("Named Clare Duwelius general manager.") == "front_office"


def test_classifies_front_office_hired():
    assert classify_transaction_type("Hired Stephanie White as head coach.") == "front_office"


def test_classifies_front_office_fired():
    assert (
        classify_transaction_type("Fired general manager Mike Thibault and coach Eric Thibault.")
        == "front_office"
    )


def test_unclassifiable_description_falls_back_to_other():
    assert classify_transaction_type("Exercised their option with C Olivia Nelson-Odoba") == "other"


def test_multi_action_description_picks_first_matching_priority_keyword():
    # "waived" outranks "signed" in the priority order -- documented
    # limitation, not a bug: a combined description only ever yields one
    # type.
    assert (
        classify_transaction_type(
            "Released F Amy Atwell. Signed F Amy Atwell to a seven-day contract."
        )
        == "released"
    )


# --- extract_raw_player_name ----------------------------------------------


def test_extracts_single_player_after_position_letter():
    assert extract_raw_player_name("Waived F Liatu King.") == "Liatu King"


def test_extracts_first_of_two_players_only():
    assert (
        extract_raw_player_name("Released F Joyner Holmes and G Jazmine Jones.") == "Joyner Holmes"
    )


def test_extracts_first_player_across_two_sentences():
    assert (
        extract_raw_player_name(
            "Activated G Aerial Powers. Released F Nikolina Milic from hardship exeption."
        )
        == "Aerial Powers"
    )


def test_stops_name_at_period_not_next_capitalized_word():
    # Regression: "Reinstated C Sylvia Fowles. Released F Nikolina Milic..."
    # must not swallow "Released" into the name.
    assert (
        extract_raw_player_name(
            "Reinstated C Sylvia Fowles. Released F Nikolina Milic from her hardship contract."
        )
        == "Sylvia Fowles"
    )


def test_extracts_name_after_plural_position_token():
    assert (
        extract_raw_player_name("Gs Marina Mabrey and DeWanna signed a contract amendment.")
        == "Marina Mabrey"
    )


def test_no_player_for_pure_front_office_move():
    assert extract_raw_player_name("Named Clare Duwelius general manager.") is None


def test_no_player_for_coach_contract_with_no_position_token():
    assert (
        extract_raw_player_name(
            "Signed head coach Cheryl Reeve to a multi-year contract extension."
        )
        is None
    )


def test_no_player_when_no_position_token_precedes_name():
    # Known limitation: a name with no leading G/F/C token is never
    # extracted, even though it's plainly present in the text.
    assert (
        extract_raw_player_name(
            "Released Jaylyn Sherrod and signed her to a second 7-day contract."
        )
        is None
    )


def test_extracts_combo_position_token():
    assert extract_raw_player_name("Waived F/C Lorela Cubaj.") == "Lorela Cubaj"


def test_extracts_name_with_accented_characters():
    assert (
        extract_raw_player_name(
            "Acquired a 2026 second-round pick, F Sika Koné and G Olivia Époupa "
            "from the Minnesota Lynx in exchange for F Myisha Hines-Allen."
        )
        == "Sika Koné"
    )


def test_short_single_word_after_position_token_is_not_a_name():
    # A lone capitalized word after a position token isn't confidently a
    # first+last name -- requires at least 2 words.
    assert extract_raw_player_name("F is out for the season.") is None
