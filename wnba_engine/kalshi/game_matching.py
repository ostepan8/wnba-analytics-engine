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
#: TWO title shapes, because Kalshi rewrote them between 2026-07-13 and
#: 2026-07-27 without changing the ticker:
#:
#:   old: "Indiana vs Phoenix winner?"
#:   new: "Las Vegas vs Chicago women's Pro Basketball game: Chicago wins?"
#:
#: Only the old one was matched, so from 2026-07-27 every KXWNBAGAME market
#: parsed as None and stopped resolving to a game -- 4,712 snapshot rows at a
#: 0.0% match rate where the preceding weeks ran 31-34%. It failed silently
#: because an unparseable title and a market we deliberately do not map are
#: the same outcome here: a NULL game_id.
#:
#: The old shape is kept rather than replaced. The database still holds rows
#: written in it, and a re-ingest that only understood the new one would
#: orphan them in the opposite direction.
_TITLE_RE = re.compile(
    r"^(.+?) vs (.+?)(?: winner\?|(?: women's Pro Basketball game)?: .+ wins\?)$"
)

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
