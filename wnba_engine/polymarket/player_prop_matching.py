"""Best-effort mapping from Polymarket player-prop markets to a player
name. Title format: "{Player Name}: {Stat} O/U {Line}", e.g. "A'ja Wilson:
Rebounds O/U 7.5". The stat word is whitelisted (rather than a generic
\\w+) so this can't accidentally match a team-matchup title like
"Minnesota Lynx vs. Connecticut Sun: O/U 167.5" (no stat word before
O/U) or a spread title like "Spread: Minnesota Lynx (-10.5)" (no O/U at
all).

Game resolution happens separately via the player's own recent team (see
entity_repo.find_recent_team_id_for_player + find_game_id_by_team_and_date),
anchored on the market's close_time -- same pattern as
polymarket/game_matching.py uses for team-matchup markets.
"""

from __future__ import annotations

import re

_STAT_WORDS = ("Points", "Rebounds", "Assists")
_TITLE_RE = re.compile(rf"^(.+?): (?:{'|'.join(_STAT_WORDS)}) O/U [\d.]+$")


def parse_player_prop_name(title: str) -> str | None:
    """Returns the player name for a player-prop market title, or None."""
    match = _TITLE_RE.match(title)
    if not match:
        return None
    return match.group(1).strip()
