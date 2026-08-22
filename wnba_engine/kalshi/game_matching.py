"""Best-effort mapping from KXWNBAGAME/KXNBAGAME markets to canonical games.

Ticker format: KX(W)NBAGAME-{YY}{MON}{DD}{concatenated team codes}, e.g.
KXWNBAGAME-26JUL09INDPHX or KXNBAGAME-26OCT20OKCSAS. Title format:
"{TeamA} vs {TeamB} winner?" (WNBA) or a bare "{TeamA} vs {TeamB}" (NBA,
confirmed live 2026-08-22 -- KXNBAGAME-26OCT20OKCSAS's event title is
exactly "Oklahoma City vs San Antonio", no trailing clause at all, unlike
any of the four WNBA shapes below). We parse the date from the ticker
(reliable, fixed-width) and team names from the title (readable city names
matching our canonical team names), rather than guessing where the
concatenated ticker abbreviations split.
"""

from __future__ import annotations

import re
from datetime import date

_TICKER_DATE_RE = re.compile(r"^KX(?:W)?NBAGAME-(\d{2})([A-Z]{3})(\d{2})")
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
#: FIVE shapes now, across two data tiers, two seasons, and (as of this
#: NBA expansion) two leagues:
#:
#:   2025 (historical tier)  "New York vs Chicago Winner?"
#:   2025 playoffs           "Las Vegas vs Phoenix (Game 4) Winner?"
#:   2026 WNBA pre-07-27     "Indiana vs Phoenix winner?"
#:   2026 WNBA post-rewrite  "... women's Pro Basketball game: Chicago wins?"
#:   2026 NBA (KXNBAGAME)    "Oklahoma City vs San Antonio" -- bare, no
#:                           trailing clause at all. Confirmed live
#:                           2026-08-22 via KXNBAGAME-26OCT20OKCSAS's real
#:                           event title. Do not assume this holds for
#:                           every NBA market forever -- Kalshi rewrote the
#:                           WNBA shape once already without changing the
#:                           ticker (see history above), so a future NBA
#:                           rewrite is exactly as plausible.
#:
#: IGNORECASE because the capitalisation of "Winner" changed between
#: seasons, and the parenthetical is optional because playoff markets name
#: the series game. The whole trailing clause is optional (not just its
#: internal alternatives) to admit the bare NBA shape. Each shape was
#: discovered by importing real titles and finding game_id NULL afterwards
#: (or, for the NBA shape, by fetching a real live event before any import
#: ran), never by reading a spec -- which is why this pattern is
#: deliberately permissive about the tail and strict about the "A vs B"
#: head that actually carries the teams.
_TITLE_RE = re.compile(
    r"^(.+?) vs (.+?)(?:\s*\(Game \d+\))?"
    r"(?:(?: winner\?|(?: women's Pro Basketball game)?: .+ wins\?))?$",
    re.IGNORECASE,
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
