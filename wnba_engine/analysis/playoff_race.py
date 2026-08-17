"""Who is in, who is out, and who is still playing for it.

**The provider's playoff_seed is a CONFERENCE seed and must not be shown as a
playoff seed.** For 2026 it reads 1-8 in the West and 1-7 in the East. The WNBA
has seeded its postseason league-wide since 2016: the top eight records make it
regardless of conference. Passing the provider's number through would show
Chicago as the 5-seed while it sits eleventh in the league.

Clinching is computed from wins and games remaining, not scraped:

  * a team can still finish ahead of X if its MAXIMUM possible wins exceed X's
    current wins;
  * if fewer than eight teams can do that, X cannot be pushed out -- clinched;
  * if eight or more teams already have more wins than X's maximum possible,
    X cannot get in -- eliminated.

**This ignores tiebreakers**, and deliberately says so wherever it is shown. The
WNBA breaks ties on head-to-head, then division and conference records; modelling
that correctly needs the full head-to-head matrix and would still be a guess for
three-way ties. What is computed here is the unambiguous part: a team that
cannot be caught, and a team that cannot catch up. A "magic number" of 1 with a
tie in play is the case this is knowingly conservative about, so the labels
describe the arithmetic rather than promising a bracket.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

# The WNBA takes the top eight records league-wide.
PLAYOFF_SPOTS = 8


@dataclass(frozen=True, slots=True)
class RaceStatus:
    """Where one team stands in the race for a postseason place."""

    team_id: int
    seed: int
    wins: int
    losses: int
    games_remaining: int
    clinched: bool
    eliminated: bool
    # Wins still needed to be uncatchable. None once settled either way.
    magic_number: int | None

    @property
    def max_wins(self) -> int:
        return self.wins + self.games_remaining


def rank_teams(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a league-wide seed and clinch status to each standings row.

    `rows` must carry team_id, wins, losses and games_remaining. Order in is
    irrelevant; order out is the standings order.
    """
    ordered = sorted(
        rows,
        key=lambda row: (
            -_rate(row),
            -int(row.get("wins") or 0),
            int(row.get("losses") or 0),
        ),
    )
    statuses = _statuses(ordered)
    leader = statuses[0] if statuses else None
    # The last team currently holding a place -- the line everyone below is
    # chasing, and the only "games behind" that describes the actual race.
    bubble = statuses[PLAYOFF_SPOTS - 1] if len(statuses) >= PLAYOFF_SPOTS else None

    return [
        {
            **row,
            "seed": status.seed,
            "games_remaining": status.games_remaining,
            "clinched": status.clinched,
            "eliminated": status.eliminated,
            "magic_number": status.magic_number,
            "in_playoff_position": status.seed <= PLAYOFF_SPOTS,
            # Computed league-wide. The provider's games_behind is measured
            # within a conference, which in a league-wide table reads as
            # nonsense: a fourth-placed team showing 0 GB because it happens to
            # lead its own conference.
            "games_behind_leader": games_behind(leader, status) if leader else None,
            "games_behind_playoff": games_behind(bubble, status) if bubble else None,
        }
        for row, status in zip(ordered, statuses, strict=True)
    ]


def games_behind(ahead: RaceStatus, behind: RaceStatus) -> float:
    """Standard games-behind: half the sum of the win gap and the loss gap.

    Negative would mean the "behind" team is actually ahead, which happens for
    everyone above the reference point, so it is clamped to zero.
    """
    raw = ((ahead.wins - behind.wins) + (behind.losses - ahead.losses)) / 2
    return max(raw, 0.0)


def _statuses(ordered: list[dict[str, Any]]) -> list[RaceStatus]:
    base = [
        RaceStatus(
            team_id=int(row["team_id"]),
            seed=index + 1,
            wins=int(row.get("wins") or 0),
            losses=int(row.get("losses") or 0),
            games_remaining=int(row.get("games_remaining") or 0),
            clinched=False,
            eliminated=False,
            magic_number=None,
        )
        for index, row in enumerate(ordered)
    ]
    return [replace(team, **_resolve(team, base)) for team in base]


def _resolve(team: RaceStatus, everyone: list[RaceStatus]) -> dict[str, Any]:
    others = [other for other in everyone if other.team_id != team.team_id]

    # Teams that could still finish with more wins than this team has now.
    contenders = [other for other in others if other.max_wins > team.wins]
    clinched = len(contenders) < PLAYOFF_SPOTS

    # Teams already beyond this team's best possible finish.
    ahead_for_good = [other for other in others if other.wins > team.max_wins]
    eliminated = len(ahead_for_good) >= PLAYOFF_SPOTS

    return {
        "clinched": clinched,
        "eliminated": eliminated,
        "magic_number": _magic_number(team, contenders) if not (clinched or eliminated) else None,
    }


def _magic_number(team: RaceStatus, contenders: list[RaceStatus]) -> int | None:
    """Wins still needed before no eighth-place challenger can catch up.

    The threshold is the PLAYOFF_SPOTS-th best challenger: a team only has to
    finish ahead of enough rivals to hold a place, not ahead of all of them.
    """
    if len(contenders) < PLAYOFF_SPOTS:
        return 0
    threshold = sorted((other.max_wins for other in contenders), reverse=True)[
        PLAYOFF_SPOTS - 1
    ]
    needed = threshold + 1 - team.wins
    if needed <= 0:
        return 0
    # Cannot need more wins than there are games left to win.
    return needed if needed <= team.games_remaining else None


def _rate(row: dict[str, Any]) -> float:
    """Win percentage, recomputed rather than trusted.

    The stored win_percentage is a provider string and is missing for a team
    that has not played; deriving it from the record keeps the sort total.
    """
    wins = int(row.get("wins") or 0)
    losses = int(row.get("losses") or 0)
    played = wins + losses
    return wins / played if played else 0.0
