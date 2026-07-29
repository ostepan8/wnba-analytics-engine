"""Unit tests for the the-odds-api PLAYER PROP parser.

Fixtures (tests/fixtures/odds_api_player_props.json,
tests/fixtures/odds_api_historical_player_props.json) are trimmed from
real responses captured live from
/v4/sports/basketball_wnba/events/{eventId}/odds/ and its /v4/historical/
counterpart (regions=us, oddsFormat=american, markets=player_points,
player_rebounds, player_assists, player_threes,
player_points_rebounds_assists) -- not hand-written JSON.

The trimming deliberately preserves one asymmetry between the two
endpoints: the CURRENT response has no `last_update` on the bookmaker
object, while the HISTORICAL one does. Several tests below pin that,
because it's the reason captured_at reads the market-level timestamp.
"""

from __future__ import annotations

import copy

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.odds_api.player_props_parser import (
    parse_current_event_props,
    parse_historical_event_props,
    prop_type_for_market,
)


def test_market_key_maps_onto_balldontlie_prop_type_vocabulary():
    """Both providers share sportsbook_player_prop_odds, so a query
    filtering prop_type='points' must match rows from either."""
    assert prop_type_for_market("player_points") == "points"
    assert prop_type_for_market("player_rebounds") == "rebounds"
    assert prop_type_for_market("player_assists") == "assists"
    assert prop_type_for_market("player_threes") == "threes"
    assert prop_type_for_market("player_points_rebounds_assists") == "points_rebounds_assists"


def test_parses_event_identity(odds_api_player_props_payload):
    parsed = parse_current_event_props(odds_api_player_props_payload)
    assert parsed.event.external_id == "c01616be622aa0fcab0ac0351d05e264"
    assert parsed.event.home_team == "Dallas Wings"
    assert parsed.event.away_team == "Atlanta Dream"


def test_over_and_under_collapse_into_one_row(odds_api_player_props_payload):
    """Two sibling outcomes for the same player+line are one prop, not
    two rows -- otherwise every prop would be double-counted."""
    parsed = parse_current_event_props(odds_api_player_props_payload)
    assists = [p for p in parsed.props if p.row.prop_type == "assists"]

    for prop in assists:
        assert prop.row.over_odds is not None
        assert prop.row.under_odds is not None
        # Two-sided market -- the single-sided `odds` column stays empty
        # (see PlayerPropOddsRow's milestone/over_under docstring).
        assert prop.row.odds is None
        assert prop.row.market_type == "over_under"


def test_player_name_is_carried_for_pipeline_resolution(odds_api_player_props_payload):
    """the-odds-api has no player id anywhere in a prop payload, so the
    name is the only handle the pipeline can resolve on."""
    parsed = parse_current_event_props(odds_api_player_props_payload)
    names = {p.player_name for p in parsed.props}

    assert names
    assert all(isinstance(n, str) and n.strip() for n in names)


def test_external_id_is_unique_per_prop(odds_api_player_props_payload):
    """The regression this id scheme exists to prevent: one bookmaker
    quotes many players across many markets on a single event, so a
    coarser id would collide under UNIQUE(external_id, captured_at) and
    silently drop rows."""
    parsed = parse_current_event_props(odds_api_player_props_payload)
    ids = [p.row.external_id for p in parsed.props]

    assert len(ids) == len(set(ids))


def test_external_id_includes_line_so_two_lines_dont_collide(
    odds_api_player_props_payload,
):
    payload = copy.deepcopy(odds_api_player_props_payload)
    market = payload["bookmakers"][0]["markets"][0]
    first = market["outcomes"][0]
    # Same player, same market, a DIFFERENT line -- a book can genuinely
    # quote this, and both must survive.
    market["outcomes"] = [
        first,
        {**first, "point": first["point"] + 5.5, "price": -200},
    ]

    parsed = parse_current_event_props(payload)
    ids = [p.row.external_id for p in parsed.props]

    assert len(ids) == len(set(ids))


def test_captured_at_reads_market_last_update_not_bookmaker(
    odds_api_player_props_payload,
):
    """The current endpoint omits last_update on the bookmaker entirely
    (verified live) -- pinned here so a future refactor can't quietly
    switch to a field that doesn't exist on this shape."""
    assert "last_update" not in odds_api_player_props_payload["bookmakers"][0]

    parsed = parse_current_event_props(odds_api_player_props_payload)
    market = odds_api_player_props_payload["bookmakers"][0]["markets"][0]
    expected = market["last_update"].replace("Z", "+00:00")

    vendor = odds_api_player_props_payload["bookmakers"][0]["key"]
    prop_type = prop_type_for_market(market["key"])
    matching = [p for p in parsed.props if p.row.vendor == vendor and p.row.prop_type == prop_type]
    assert matching
    assert all(p.row.updated_at.isoformat() == expected for p in matching)


def test_historical_payload_unwraps_data_object(
    odds_api_historical_player_props_payload,
):
    """Historical props wrap a single event OBJECT under "data" -- not the
    ARRAY the bulk historical odds endpoint returns."""
    parsed = parse_historical_event_props(odds_api_historical_player_props_payload)

    assert parsed.event.home_team == "Chicago Sky"
    assert parsed.props


def test_historical_bookmaker_does_carry_last_update(
    odds_api_historical_player_props_payload,
):
    """The asymmetry with the current endpoint, pinned so the fixture
    can't be "tidied" into agreeing with it."""
    bookmaker = odds_api_historical_player_props_payload["data"]["bookmakers"][0]
    assert "last_update" in bookmaker


def test_non_player_markets_are_ignored(odds_api_player_props_payload):
    """Forward-compatible with the-odds-api returning a market this
    schema has no prop_type for."""
    payload = copy.deepcopy(odds_api_player_props_payload)
    payload["bookmakers"][0]["markets"].append(
        {
            "key": "h2h",
            "last_update": "2026-07-29T16:08:40Z",
            "outcomes": [{"name": "Dallas Wings", "price": -150}],
        }
    )

    parsed = parse_current_event_props(payload)

    assert all(p.row.prop_type != "h2h" for p in parsed.props)


def test_event_with_no_bookmakers_still_resolves(odds_api_player_props_payload):
    """A freshly-listed game nobody has priced yet is legitimate -- the
    event still needs to resolve to a canonical game."""
    payload = copy.deepcopy(odds_api_player_props_payload)
    del payload["bookmakers"]

    parsed = parse_current_event_props(payload)

    assert parsed.props == ()
    assert parsed.event.external_id == "c01616be622aa0fcab0ac0351d05e264"


def test_rejects_non_object_payload():
    with pytest.raises(ProviderValidationError):
        parse_current_event_props([])


def test_rejects_historical_payload_without_data():
    with pytest.raises(ProviderValidationError):
        parse_historical_event_props({"timestamp": "2025-08-15T17:55:38Z"})


def test_rejects_outcome_missing_player_description(odds_api_player_props_payload):
    """description IS the player -- a missing one is unparseable, not a
    row to silently drop."""
    payload = copy.deepcopy(odds_api_player_props_payload)
    del payload["bookmakers"][0]["markets"][0]["outcomes"][0]["description"]

    with pytest.raises(ProviderValidationError):
        parse_current_event_props(payload)
