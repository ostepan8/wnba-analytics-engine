"""Unit tests for the ESPN transactions parser.

Fixtures are real, trimmed (team logo/link noise stripped) payloads
captured live:
- espn_transactions_2022.json: full season=2022 response (47 rows,
  pageCount=1) from /wnba/v1 ... /transactions?season=2022&limit=200.
- espn_transactions_2025_page2.json: first 5 rows of the real page=2
  response for season=2025 (the one real season observed needing
  pagination -- count=220, pageCount=2).
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.espn.transactions_parser import page_count, parse_transactions_page


def test_parses_all_rows(espn_transactions_2022_payload):
    rows = parse_transactions_page(espn_transactions_2022_payload)
    assert len(rows) == 47


def test_parses_first_row_fields(espn_transactions_2022_payload):
    rows = parse_transactions_page(espn_transactions_2022_payload)
    first = rows[0]
    assert first.transaction_date == datetime(2022, 12, 15, 8, 0, tzinfo=UTC)
    assert first.description == (
        "Signed general manager Dan Padover and head coach Tanisha Wright "
        "to five-year contract extensions through the 2027 season."
    )
    assert first.team_external_id == "20"
    assert first.team_name == "Atlanta Dream"


def test_parses_second_page_fixture(espn_transactions_2025_page2_payload):
    rows = parse_transactions_page(espn_transactions_2025_page2_payload)
    assert len(rows) == 5
    assert rows[0].team_name == "Indiana Fever"


def test_page_count_reads_real_pagecount(espn_transactions_2022_payload):
    assert page_count(espn_transactions_2022_payload) == 1


def test_page_count_reads_multi_page_pagecount(espn_transactions_2025_page2_payload):
    assert page_count(espn_transactions_2025_page2_payload) == 2


def test_page_count_defaults_to_one_when_missing():
    assert page_count({}) == 1


def test_page_count_defaults_to_one_for_non_mapping():
    assert page_count(["not", "a", "dict"]) == 1


def test_missing_transactions_key_returns_empty_tuple():
    assert parse_transactions_page({"count": 0}) == ()


def test_non_mapping_payload_raises():
    with pytest.raises(ProviderValidationError):
        parse_transactions_page(["not", "a", "dict"])


def test_row_missing_date_raises(espn_transactions_2022_payload):
    broken = copy.deepcopy(espn_transactions_2022_payload)
    del broken["transactions"][0]["date"]
    with pytest.raises(ProviderValidationError, match="date"):
        parse_transactions_page(broken)


def test_row_missing_description_raises(espn_transactions_2022_payload):
    broken = copy.deepcopy(espn_transactions_2022_payload)
    del broken["transactions"][0]["description"]
    with pytest.raises(ProviderValidationError, match="description"):
        parse_transactions_page(broken)


def test_row_missing_team_raises(espn_transactions_2022_payload):
    broken = copy.deepcopy(espn_transactions_2022_payload)
    del broken["transactions"][0]["team"]
    with pytest.raises(ProviderValidationError, match="team"):
        parse_transactions_page(broken)


def test_row_missing_team_id_raises(espn_transactions_2022_payload):
    broken = copy.deepcopy(espn_transactions_2022_payload)
    del broken["transactions"][0]["team"]["id"]
    with pytest.raises(ProviderValidationError, match="id"):
        parse_transactions_page(broken)


def test_non_mapping_row_raises(espn_transactions_2022_payload):
    broken = copy.deepcopy(espn_transactions_2022_payload)
    broken["transactions"][0] = "not a dict"
    with pytest.raises(ProviderValidationError, match="transaction must be an object"):
        parse_transactions_page(broken)
