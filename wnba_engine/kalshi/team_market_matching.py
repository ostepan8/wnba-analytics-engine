"""Best-effort mapping from Kalshi team-level per-game derivative markets
(spreads, totals, quarter/half winners, overtime -- KXWNBASPREAD,
KXWNBATOTAL, KXWNBA1QSPREAD, KXWNBA1HWINNER, KXWNBAOT, ...) to team
names + date. Distinct from game_matching.py (KXWNBAGAME's own
"X vs Y winner?" shape) and player_prop_matching.py (per-player props) --
these derivative markets use two different title shapes depending on the
series, confirmed against real captured titles:

- Two-team ("X vs Y[: ...]?"): totals, quarter spreads, quarter/half
  winners, overtime, e.g. "Golden State vs Toronto: 1st Quarter Total?",
  "Golden State vs Toronto on Jul 8, 2026: Overtime?"
- Single-team ("X wins by ..." / "Will X win the ..."): full-game and
  half-game spreads, e.g. "Indiana wins by over 7.5 points?",
  "Will Atlanta win the 2H by over 1.5 points?"

Team names here are short city forms ("Atlanta", not "Atlanta Dream"),
so resolution needs a substring team lookup (see
entity_repo.find_team_by_name_fragment), not the exact-match
find_team_by_name.

Ticker date extraction duplicates player_prop_matching.py's generalized
regex rather than importing it -- same self-contained-module pattern
game_matching.py already uses for its own (narrower) copy.
"""

from __future__ import annotations

import re
from datetime import date

_TICKER_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})[A-Z]*$")
_TWO_TEAM_RE = re.compile(r"^(.+?)\s+vs\.?\s+(.+?)(?:\s+on\s+.+|:.*)?$")
_SINGLE_TEAM_FULL_RE = re.compile(r"^(.+?) wins by over [\d.]+ points\??$")
_SINGLE_TEAM_HALF_RE = re.compile(r"^Will (.+?) win the [12]H by over [\d.]+ points\?$")

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip


def _parse_ticker_date(event_external_id: str) -> date | None:
    match = _TICKER_DATE_RE.search(event_external_id)
    if not match:
        return None
    yy, mon, dd = match.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        return date(2000 + int(yy), month, int(dd))
    except ValueError:
        return None


def parse_two_team_market(event_external_id: str, title: str) -> tuple[date, str, str] | None:
    """Returns (game_date, team_a, team_b) for a two-team derivative
    market title (totals, quarter spreads, quarter/half winners,
    overtime), or None if either input doesn't match that shape."""
    game_date = _parse_ticker_date(event_external_id)
    match = _TWO_TEAM_RE.match(title)
    if game_date is None or not match:
        return None
    return game_date, match.group(1).strip(), match.group(2).strip()


def parse_single_team_market(event_external_id: str, title: str) -> tuple[date, str] | None:
    """Returns (game_date, team) for a single-team derivative market title
    (full-game and half-game spreads), or None."""
    game_date = _parse_ticker_date(event_external_id)
    if game_date is None:
        return None
    match = _SINGLE_TEAM_FULL_RE.match(title) or _SINGLE_TEAM_HALF_RE.match(title)
    if not match:
        return None
    return game_date, match.group(1).strip()
