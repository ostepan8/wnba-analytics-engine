"""Best-effort mapping from Polymarket team-level derivative markets to
team names, for the two shapes game_matching.py's parse_matchup_teams
deliberately excludes (it bails out on any colon in the title, since
player props and these two also use one):

- Total: "{TeamA} vs. {TeamB}: O/U {N}", e.g.
  "Golden State Valkyries vs. Toronto Tempo: O/U 165.5" -- team names are
  Polymarket's own full canonical names, same as the no-colon matchup
  markets game_matching.py already handles.
- Spread: "Spread: {Team} ({+/-N})", e.g. "Spread: Atlanta Dream (-10.5)"
  -- single team, also a full canonical name.
"""

from __future__ import annotations

import re

_TOTAL_RE = re.compile(r"^(.+?)\s+vs\.?\s+(.+?):\s*O/U\s+[\d.]+$")
_SPREAD_RE = re.compile(r"^Spread:\s*(.+?)\s*\([+-][\d.]+\)$")


def parse_total_market_teams(title: str) -> tuple[str, str] | None:
    """Returns (team_a, team_b) for a "{TeamA} vs. {TeamB}: O/U {N}"
    total-market title, or None."""
    match = _TOTAL_RE.match(title)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def parse_spread_market_team(title: str) -> str | None:
    """Returns the team name for a "Spread: {Team} ({+/-N})" market
    title, or None."""
    match = _SPREAD_RE.match(title)
    if not match:
        return None
    return match.group(1).strip()
