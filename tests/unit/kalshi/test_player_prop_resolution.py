"""One Kalshi event holds many players' props, and each names its own.

The resolver cached its answer per EVENT, which is correct for the game a market
belongs to -- every market under an event is the same game -- and wrong for the
player, who appears only in the market title. The first market's player was
resolved and then stamped onto every other market in the event: 76,776 of
179,882 stored prop rows carried the wrong player, with a single id standing in
for a dozen different people.

The failure is invisible in aggregate. Row counts, freshness and price ranges
all look correct; only reading a name next to a price shows it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from wnba_engine.pipeline.kalshi_ingest import _resolve_player_prop_ids


@dataclass(frozen=True)
class FakeSnapshot:
    market_external_id: str
    event_external_id: str | None
    title: str


EVENT = "KXWNBAPTS-26AUG15ATL"


@pytest.fixture
def resolver(monkeypatch):
    """Stand in for the database: name -> id, and no team/game lookup."""
    players = {
        "Rhyne Howard": 29,
        "Allisha Gray": 41,
        "Brionna Jones": 55,
        "Sonia Citron": 239,
    }
    calls: list[str] = []

    def find_player_by_name(_conn, name: str):
        calls.append(name)
        return players.get(name)

    monkeypatch.setattr(
        "wnba_engine.pipeline.kalshi_ingest.entity_repo.find_player_by_name",
        find_player_by_name,
    )
    monkeypatch.setattr(
        "wnba_engine.pipeline.kalshi_ingest.entity_repo.find_recent_team_id_for_player",
        lambda _conn, _player_id: None,
    )
    return calls


def test_each_market_resolves_its_own_player(resolver) -> None:
    """The regression. Three players under one event must produce three ids."""
    snapshots = [
        FakeSnapshot("M-HOWARD-15", EVENT, "Rhyne Howard: 15+ points"),
        FakeSnapshot("M-GRAY-15", EVENT, "Allisha Gray: 15+ points"),
        FakeSnapshot("M-JONES-10", EVENT, "Brionna Jones: 10+ points"),
    ]
    players, _games = _resolve_player_prop_ids(None, snapshots)

    assert players == {"M-HOWARD-15": 29, "M-GRAY-15": 41, "M-JONES-10": 55}
    # And emphatically NOT one player smeared across all three.
    assert len(set(players.values())) == 3


def test_the_same_player_at_several_lines_is_resolved_once(resolver) -> None:
    """The caching this replaced was there for a reason -- a player carries a
    market per threshold. Keyed on the title, those still collapse to one
    lookup, so the fix does not trade correctness for a lookup per row."""
    snapshots = [
        FakeSnapshot("M-HOWARD-10", EVENT, "Rhyne Howard: 10+ points"),
        FakeSnapshot("M-HOWARD-10-DUP", EVENT, "Rhyne Howard: 10+ points"),
        FakeSnapshot("M-HOWARD-10-DUP2", EVENT, "Rhyne Howard: 10+ points"),
    ]
    _resolve_player_prop_ids(None, snapshots)
    assert resolver.count("Rhyne Howard") == 1


def test_an_unknown_player_leaves_the_market_unmapped(resolver) -> None:
    """Unmapped is correct. Attaching the wrong id would be worse than a NULL,
    which is exactly what the old grouping did."""
    snapshots = [
        FakeSnapshot("M-KNOWN", EVENT, "Rhyne Howard: 15+ points"),
        FakeSnapshot("M-UNKNOWN", EVENT, "Someone Notinourdb: 15+ points"),
    ]
    players, _games = _resolve_player_prop_ids(None, snapshots)
    assert players == {"M-KNOWN": 29}


def test_a_market_with_no_event_is_skipped(resolver) -> None:
    snapshots = [FakeSnapshot("M-ORPHAN", None, "Rhyne Howard: 15+ points")]
    players, _games = _resolve_player_prop_ids(None, snapshots)
    assert players == {}


def test_a_non_prop_title_resolves_to_nothing(resolver) -> None:
    """Team and futures markets share the feed and must not be forced into a
    player shape."""
    snapshots = [FakeSnapshot("M-TEAM", EVENT, "Atlanta Dream wins")]
    players, _games = _resolve_player_prop_ids(None, snapshots)
    assert players == {}
