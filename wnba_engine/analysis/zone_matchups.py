"""Which of tonight's rotation players has a real zone advantage, and where.

The question this answers: does either team's shooter line up against a soft
spot in the other team's defence? Both sides are the same computation --
a player's own season shooting by zone against their tonight's opponent's
season defensive shooting by zone, both measured against a league baseline --
run for every rotation player on both rosters and ranked together.

**Season-long on both sides, not this specific pairing.** shot_locations has
nowhere near enough shots between one player and one opponent to say anything
about that matchup specifically -- a rotation player might see a given
opponent two or three times a season. This uses the same volume-backed
comparison PlayerMatchup.tsx does for one player on their own page, just
computed here for a whole game's worth of players at once so the frontend
does not fire a dozen-plus requests to build the same table.

**Thresholds mirror PlayerMatchup.tsx deliberately** (ZONE_MIN_ATTEMPTS=15,
EDGE_THRESHOLD=0.03): an efficient player clears league average in nearly
every zone by construction, so `> 0` alone would flag almost the whole floor
as an edge. Keep these two constants in sync if either changes -- they are
independent implementations of the same rule, not a shared import, because
one runs in the browser and one runs here.

Not a forecast. This describes where a player has shot well and where a
defence has allowed shooting, both over a season; it says nothing about what
either team scouts or adjusts to for one specific game.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ZONE_MIN_ATTEMPTS = 15
EDGE_THRESHOLD = 0.03

# A "rotation" for this purpose -- deep enough to catch a sixth or seventh
# player who's a live matchup, shallow enough that a table of edges stays
# readable rather than becoming the whole roster.
PLAYERS_PER_TEAM = 6


@dataclass(frozen=True, slots=True)
class ZoneEdge:
    """One player's real advantage in one zone against tonight's opponent."""

    player_id: int
    full_name: str
    team_id: int
    opponent_team_id: int
    zone: str
    player_rate: float
    defense_rate: float
    league_rate: float
    player_edge: float
    defense_weak: float

    @property
    def combined_edge(self) -> float:
        return self.player_edge + self.defense_weak


def _zone_rate(row: dict[str, Any] | None) -> float | None:
    """None below the volume floor, on either side of the comparison -- a
    thin sample is excluded rather than shown as a confident weak rate."""
    if row is None:
        return None
    attempts = int(row["attempts"])
    if attempts < ZONE_MIN_ATTEMPTS:
        return None
    return int(row["makes"]) / attempts


def compute_zone_edges(
    *,
    rosters: dict[int, list[dict[str, Any]]],
    player_zones: dict[int, list[dict[str, Any]]],
    defense_zones: dict[int, list[dict[str, Any]]],
    league_zones: list[dict[str, Any]],
    opponent_of: dict[int, int],
) -> list[ZoneEdge]:
    """Every rotation player's real zone edges against their own next
    opponent, both teams combined and ranked together by size of edge.

    `rosters` and `defense_zones` are keyed by team_id, `player_zones` by
    player_id -- each already ordered/filtered by the caller (rosters by
    minutes, zones already restricted to the players who matter).
    """
    league_by_zone = {row["zone"]: row for row in league_zones}
    defense_by_team_zone = {
        team_id: {row["zone"]: row for row in rows} for team_id, rows in defense_zones.items()
    }
    zones_by_player = {
        player_id: {row["zone"]: row for row in rows} for player_id, rows in player_zones.items()
    }

    edges: list[ZoneEdge] = []
    for team_id, roster in rosters.items():
        opponent_id = opponent_of.get(team_id)
        if opponent_id is None:
            continue
        opponent_defense = defense_by_team_zone.get(opponent_id, {})
        if not opponent_defense:
            continue

        for player in roster[:PLAYERS_PER_TEAM]:
            player_id = int(player["player_id"])
            zones = zones_by_player.get(player_id, {})
            for zone_name, player_zone in zones.items():
                league_rate = _zone_rate(league_by_zone.get(zone_name))
                defense_rate = _zone_rate(opponent_defense.get(zone_name))
                player_rate = _zone_rate(player_zone)
                if league_rate is None or defense_rate is None or player_rate is None:
                    continue

                player_edge = player_rate - league_rate
                defense_weak = defense_rate - league_rate
                if player_edge <= EDGE_THRESHOLD or defense_weak <= EDGE_THRESHOLD:
                    continue

                edges.append(
                    ZoneEdge(
                        player_id=player_id,
                        full_name=player["full_name"],
                        team_id=team_id,
                        opponent_team_id=opponent_id,
                        zone=zone_name,
                        player_rate=player_rate,
                        defense_rate=defense_rate,
                        league_rate=league_rate,
                        player_edge=player_edge,
                        defense_weak=defense_weak,
                    )
                )

    return sorted(edges, key=lambda edge: edge.combined_edge, reverse=True)
