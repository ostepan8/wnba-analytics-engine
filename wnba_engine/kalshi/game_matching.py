"""Best-effort mapping from KXWNBAGAME markets to canonical games.

Ticker format: KXWNBAGAME-{YY}{MON}{DD}{concatenated team codes}, e.g.
KXWNBAGAME-26JUL09INDPHX. Title format: "{TeamA} vs {TeamB} winner?". We
parse the date from the ticker (reliable, fixed-width) and team names from
the title (readable city names matching our canonical team names), rather
than guessing where the concatenated ticker abbreviations split.
"""

from __future__ import annotations

import re
from datetime import date

_TICKER_DATE_RE = re.compile(r"^KXWNBAGAME-(\d{2})([A-Z]{3})(\d{2})")
_TITLE_RE = re.compile(r"^(.+?) vs (.+?) winner\?$")

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip


def parse_matchup(event_external_id: str, title: str) -> tuple[date, str, str] | None:
    """Returns (game_date, team_a, team_b), or None if either input doesn't
    match the KXWNBAGAME shape (e.g. it's a different series like
    KXWNBATOTAL, or a props/futures market)."""
    ticker_match = _TICKER_DATE_RE.match(event_external_id)
    title_match = _TITLE_RE.match(title)
    if not ticker_match or not title_match:
        return None
    yy, mon, dd = ticker_match.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        game_date = date(2000 + int(yy), month, int(dd))
    except ValueError:
        return None
    return game_date, title_match.group(1).strip(), title_match.group(2).strip()
