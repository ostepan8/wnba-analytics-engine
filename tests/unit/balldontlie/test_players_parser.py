"""Unit tests for the balldontlie /wnba/v1/players sweep parser.

Fixture (tests/fixtures/balldontlie_players.json) is three real captured
rows from a live API call: an all-null-bio historical player (Tina
Thompson), a partial-bio player with only jersey_number populated
(Layshia Clarendon), and a full-bio current player (DeWanna Bonner) -- not
hand-written JSON.
"""

from __future__ import annotations

import pytest

from wnba_engine.balldontlie.players_parser import parse_players
from wnba_engine.errors import ProviderValidationError


def test_parses_all_rows(balldontlie_players_payload):
    players = parse_players(balldontlie_players_payload)
    assert len(players) == 3


def test_parses_sparse_bio_row(balldontlie_players_payload):
    players = parse_players(balldontlie_players_payload)
    thompson = players[0]
    assert thompson.external_id == "1"
    assert thompson.full_name == "Tina Thompson"
    assert thompson.position == "Forward"
    assert thompson.height is None
    assert thompson.weight is None
    assert thompson.jersey_number is None
    assert thompson.college is None
    assert thompson.age is None


def test_parses_partial_bio_row(balldontlie_players_payload):
    players = parse_players(balldontlie_players_payload)
    clarendon = players[1]
    assert clarendon.external_id == "336"
    assert clarendon.full_name == "Layshia Clarendon"
    assert clarendon.jersey_number == "5"
    assert clarendon.height is None
    assert clarendon.weight is None
    assert clarendon.college is None
    assert clarendon.age is None


def test_parses_full_bio_row(balldontlie_players_payload):
    players = parse_players(balldontlie_players_payload)
    bonner = players[2]
    assert bonner.external_id == "242"
    assert bonner.full_name == "DeWanna Bonner"
    assert bonner.position == "F"
    assert bonner.height == "6' 4\""
    assert bonner.weight == "140 lbs"
    assert bonner.jersey_number == "24"
    assert bonner.college == "Auburn"
    assert bonner.age == 38


def test_missing_data_key_raises():
    with pytest.raises(ProviderValidationError):
        parse_players({})


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_players([])


def test_non_mapping_row_raises():
    with pytest.raises(ProviderValidationError):
        parse_players({"data": ["not-a-mapping"]})
