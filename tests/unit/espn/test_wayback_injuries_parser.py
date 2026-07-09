"""Unit tests for the Wayback-archived ESPN injuries page parser.

Fixture (tests/fixtures/espn_wayback_injuries.html) wraps a trimmed, real
captured snapshot payload (2026-01-01 archive of espn.com/wnba/injuries) in
a minimal HTML shell -- not hand-written JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wnba_engine.errors import ProviderValidationError
from wnba_engine.espn.wayback_injuries_parser import parse_wayback_injuries_page

_SNAPSHOT_CAPTURED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_parses_all_entries(espn_wayback_injuries_html):
    entries = parse_wayback_injuries_page(
        espn_wayback_injuries_html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT
    )
    assert len(entries) == 4


def test_parses_player_and_team_abbreviation(espn_wayback_injuries_html):
    entries = parse_wayback_injuries_page(
        espn_wayback_injuries_html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT
    )
    reese = next(e for e in entries if e.player.full_name == "Angel Reese")
    assert reese.player.external_id == "4433402"
    assert reese.player.position == "F"
    assert reese.team_abbreviation == "CHI"


def test_parses_status(espn_wayback_injuries_html):
    entries = parse_wayback_injuries_page(
        espn_wayback_injuries_html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT
    )
    reese = next(e for e in entries if e.player.full_name == "Angel Reese")
    assert reese.status == "Out"
    assert reese.status_type == "INJURY_STATUS_OUT"
    assert reese.captured_at == _SNAPSHOT_CAPTURED_AT


def test_reported_at_prefers_description_date_over_item_date_field(espn_wayback_injuries_html):
    """Real observed quirk: the item's own "date" field ("May 1") was stale
    for a September injury still marked Out months later; the description's
    own "Sep 11: ..." prefix is the accurate one. Snapshot year is 2026, and
    September is in the snapshot's past, so no year-wrap needed."""
    entries = parse_wayback_injuries_page(
        espn_wayback_injuries_html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT
    )
    reese = next(e for e in entries if e.player.full_name == "Angel Reese")
    assert reese.reported_at == datetime(2025, 9, 11, tzinfo=UTC)


def test_reported_at_falls_back_to_item_date_field_without_description_prefix():
    """No description text at all -> falls back to the item's own date
    field with year inferred from the snapshot."""
    html = _html_with_single_item(
        date="Jun 6", description="", snapshot_month_day="2026-07-08"
    )
    entries = parse_wayback_injuries_page(
        html, snapshot_captured_at=datetime(2026, 7, 8, tzinfo=UTC)
    )
    assert entries[0].reported_at == datetime(2026, 6, 6, tzinfo=UTC)


def test_reported_at_wraps_to_previous_year_when_future_of_snapshot():
    """A "Dec 30" report read back from an early-January snapshot must be
    from the previous year, not the future."""
    html = _html_with_single_item(date="Dec 30", description="")
    entries = parse_wayback_injuries_page(
        html, snapshot_captured_at=datetime(2026, 1, 5, tzinfo=UTC)
    )
    assert entries[0].reported_at == datetime(2025, 12, 30, tzinfo=UTC)


def test_reported_at_falls_back_to_snapshot_date_when_unparseable():
    html = _html_with_single_item(date="not a date", description="")
    captured_at = datetime(2026, 7, 8, tzinfo=UTC)
    entries = parse_wayback_injuries_page(html, snapshot_captured_at=captured_at)
    assert entries[0].reported_at == captured_at


def test_missing_embedded_payload_raises():
    with pytest.raises(ProviderValidationError, match="__espnfitt__"):
        parse_wayback_injuries_page(
            "<html><body>not the right page</body></html>",
            snapshot_captured_at=_SNAPSHOT_CAPTURED_AT,
        )


def test_missing_athlete_id_raises():
    html = (
        "<script>window['__espnfitt__']={\"page\": {\"content\": {\"injuries\": ["
        '{"displayName": "Chicago Sky", '
        '"logo": "https://a.espncdn.com/i/teamlogos/wnba/500/chi.png", '
        '"items": [{"type": {"name": "INJURY_STATUS_OUT"}, '
        '"athlete": {"name": "Angel Reese", "href": "https://www.espn.com/no-id-here", '
        '"position": "F"}, "statusDesc": "Out", "date": "Jun 6", "description": ""}]}'
        "]}}};</script>"
    )
    with pytest.raises(ProviderValidationError, match="athlete id"):
        parse_wayback_injuries_page(html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT)


def test_unparseable_team_logo_raises():
    html = (
        "<script>window['__espnfitt__']={\"page\": {\"content\": {\"injuries\": ["
        '{"displayName": "Chicago Sky", "logo": "not-a-logo-url", "items": []}'
        "]}}};</script>"
    )
    with pytest.raises(ProviderValidationError, match="abbreviation"):
        parse_wayback_injuries_page(html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT)


@pytest.mark.parametrize(
    ("logo_slug", "expected_abbreviation"),
    [
        ("conn", "CON"),  # Connecticut Sun: canonical abbreviation is CON, not CONN
        ("gsv", "GS"),  # Golden State Valkyries: canonical abbreviation is GS, not GSV
        ("chi", "CHI"),  # unaliased case still passes through unchanged
    ],
)
def test_known_logo_abbreviation_aliases_normalize_to_canonical(logo_slug, expected_abbreviation):
    """Regression test: discovered via a real backfill run where ~1,300
    entries across 540 snapshot days were silently unresolved because these
    two teams' logo filenames don't match their canonical abbreviation."""
    html = (
        "<script>window['__espnfitt__']={\"page\": {\"content\": {\"injuries\": ["
        f'{{"displayName": "Team", '
        f'"logo": "https://a.espncdn.com/i/teamlogos/wnba/500/{logo_slug}.png", '
        '"items": []}'
        "]}}};</script>"
    )
    entries = parse_wayback_injuries_page(html, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT)
    assert entries == ()  # no items in this fixture, just checking it doesn't raise

    # Exercise the abbreviation resolution directly via a real item too.
    html_with_item = _html_with_single_item(date="Jun 6", description="").replace(
        "chi.png", f"{logo_slug}.png"
    )
    entries_with_item = parse_wayback_injuries_page(
        html_with_item, snapshot_captured_at=_SNAPSHOT_CAPTURED_AT
    )
    assert entries_with_item[0].team_abbreviation == expected_abbreviation


def _html_with_single_item(*, date: str, description: str, snapshot_month_day: str = "") -> str:
    del snapshot_month_day  # kept for readability at call sites, unused
    payload = (
        '{"page": {"content": {"injuries": ['
        '{"displayName": "Chicago Sky", '
        '"logo": "https://a.espncdn.com/i/teamlogos/wnba/500/chi.png", '
        '"items": [{"type": {"name": "INJURY_STATUS_OUT"}, '
        '"athlete": {"name": "Angel Reese", '
        '"href": "https://www.espn.com/wnba/player/_/id/4433402/angel-reese", '
        '"position": "F"}, "statusDesc": "Out", '
        f'"date": "{date}", "description": "{description}"}}]}}'
        "]}}}"
    )
    return f"<script>window['__espnfitt__']={payload};</script>"
