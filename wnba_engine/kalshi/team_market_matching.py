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

#: Matches an EVENT ticker ("KXWNBASPREAD-26AUG02TORGS") and also a
#: MARKET ticker, which appends an outcome segment
#: ("KXWNBASPREAD-26AUG02TORGS-GS26"). Callers hold different halves of
#: the identity: kalshi_ingest has the event ticker, relink-market-games
#: only has the market one. While this was end-anchored the market form
#: matched nothing and the repair resolved zero of 68,963 spread bars.
_TICKER_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})[A-Z]*(?:-[A-Z0-9]+)?$")
#: The sport-description clause Kalshi inserted into titles between
#: 2026-07-13 and 2026-07-27:
#:
#:   before: "Golden State vs Toronto: 1st Quarter Total?"
#:   after:  "Atlanta vs Dallas women's Pro Basketball game: Over 166.5 points?"
#:
#: Without it in the pattern this regex still MATCHED, which is why the
#: breakage was worse here than in game_matching: the non-greedy second
#: group simply grew to swallow the clause, yielding team_b = "Dallas
#: women's Pro Basketball game". A wrong team name fails the downstream
#: substring lookup just as silently as no match at all -- 13,330
#: KXWNBATOTAL rows since 2026-07-27, against 633/1146 the week before.
_SPORT_CLAUSE = r"(?:\s+women's Pro Basketball game)?"
_TWO_TEAM_RE = re.compile(rf"^(.+?)\s+vs\.?\s+(.+?){_SPORT_CLAUSE}(?:\s+on\s+.+|:.*)?$")
#: "the game" is optional because Kalshi inserted it in the 2026-07-27
#: title rewrite -- the third matcher that change broke, and the one
#: missed when game_matching and the two-team pattern were fixed:
#:
#:     before: "Indiana wins by over 7.5 points?"
#:     after:  "Las Vegas wins the game by over 19.5 points?"
_SINGLE_TEAM_FULL_RE = re.compile(
    r"^(.+?) wins(?: the game)? by over [\d.]+ points\??$"
)
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
