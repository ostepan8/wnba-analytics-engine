"""Best-effort mapping from Polymarket team-matchup markets to canonical
games. Player-prop markets ("Player Name: Stat O/U N.N") are deliberately
excluded here -- mapping those needs a player crosswalk too, which is
separate follow-up work, not something to guess at.
"""

from __future__ import annotations

import re

_MATCHUP_RE = re.compile(r"^(.+?)\s+vs\.?\s+(.+?)$")


def parse_matchup_teams(title: str) -> tuple[str, str] | None:
    """Returns (team_a, team_b) for a team-vs-team market title, or None."""
    if ":" in title:  # player props are "Name: Stat O/U N.N"
        return None
    match = _MATCHUP_RE.match(title)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()
