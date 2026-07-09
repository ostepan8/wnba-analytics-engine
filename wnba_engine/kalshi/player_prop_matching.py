"""Best-effort mapping from Kalshi per-game player-prop markets (series
like KXWNBAPTS, KXWNBAREB, KXWNBA3PT, KXWNBAAST) to a player name + date.

Unlike KXWNBAGAME, prop titles carry no team names at all -- "Alyssa
Thomas: 6+ rebounds" -- and the ticker's concatenated team codes are
ambiguous to split (e.g. "GSTOR" could be GS+TOR or G+STOR). So this module
only extracts (game_date, player_name); resolving the actual game happens
via the player's own recent team (see entity_repo.find_recent_team_id_for_player
+ find_game_id_by_team_and_date), not by decoding the ticker's team codes.

No series prefix whitelist is needed: the title shape "{Name}: {N}+ {stat}"
doesn't collide with any other Kalshi market title in this repo (team
markets use "{Team} wins by ..." / "{Team} vs {Team}" phrasing with no
colon; season-long award/leader markets use "Will ..." phrasing). The
ticker-date match is a second, independent gate -- season-long tickers
(e.g. KXWNBAMVP-26) don't carry the trailing {YY}{MON}{DD}{teamcodes}
suffix this regex requires.
"""

from __future__ import annotations

import re
from datetime import date

_TICKER_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})[A-Z]*$")
_TITLE_RE = re.compile(r"^(.+?):\s*\d+\+\s+\w+$")

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip


def parse_player_prop(event_external_id: str, title: str) -> tuple[date, str] | None:
    """Returns (game_date, player_name), or None if either input doesn't
    match the per-game player-prop shape (e.g. it's a team market, a
    season-long award/leader market, or a futures series)."""
    title_match = _TITLE_RE.match(title)
    ticker_match = _TICKER_DATE_RE.search(event_external_id)
    if not title_match or not ticker_match:
        return None
    yy, mon, dd = ticker_match.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        game_date = date(2000 + int(yy), month, int(dd))
    except ValueError:
        return None
    return game_date, title_match.group(1).strip()
