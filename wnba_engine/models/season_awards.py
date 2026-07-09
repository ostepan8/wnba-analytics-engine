"""Ground-truth WNBA season award winner, as hand-researched from
Wikipedia/WNBA.com/basketball-reference.

See db/migrations/0017_season_awards.sql for the table this feeds and
wnba_engine/pipeline/season_awards_seed.py for the researched data itself.
"""

from __future__ import annotations

from dataclasses import dataclass

# team_selection sentinel for single-winner awards and All-Rookie (a single
# unified team, not split first/second) -- matches the column's DB default,
# see 0017_season_awards.sql for why this is a NOT NULL sentinel rather than
# NULL.
NO_TEAM_SELECTION = "na"


@dataclass(frozen=True, slots=True)
class AwardWinner:
    season: int
    award: str
    raw_name: str
    source: str
    team_selection: str = NO_TEAM_SELECTION
    # Coach of the Year only: the team name (as it appears in the `teams`
    # table) the coach led that season, resolved to team_id via
    # entity_repo.find_team_by_name at seed time. None for every other
    # award -- team_id is documented as optional for player awards (see
    # migration comment) and left unpopulated here to avoid guessing at a
    # single "the" team for players who could plausibly be tied to more
    # than one team concept (award context vs. current roster).
    coach_team_name: str | None = None
