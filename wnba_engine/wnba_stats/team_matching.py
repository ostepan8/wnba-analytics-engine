"""stats.wnba.com team abbreviations -> ours.

Eight of thirteen 2025 abbreviations already agree; five do not, and the
disagreement is not a pattern that can be derived (GSV/GS drops a letter,
WAS/WSH moves one). So it is a table, verified against the 2025 game log on
2026-08-04:

    ours   theirs
    GS     GSV      Golden State Valkyries
    LA     LAS      Los Angeles Sparks
    LV     LVA      Las Vegas Aces
    NY     NYL      New York Liberty
    WSH    WAS      Washington Mystics

POR and TOR appear only on our side because Portland and Toronto joined in
2026, after the season this was checked against; they are absent here
rather than wrong, and `to_canonical` returning the input unchanged is the
right behaviour for them -- both leagues use the same three letters.

Deliberately NOT a fuzzy or prefix match. "LA" is a prefix of "LAS" but
also of nothing else today, and that accident is exactly the kind of thing
that breaks when a franchise is added. An unknown abbreviation should fall
through and fail to resolve loudly rather than match the wrong team.
"""

from __future__ import annotations

#: stats.wnba.com abbreviation -> the abbreviation in our `teams` table.
STATS_TO_CANONICAL: dict[str, str] = {
    "GSV": "GS",
    "LAS": "LA",
    "LVA": "LV",
    "NYL": "NY",
    "WAS": "WSH",
    # Phoenix is PHO for 1997-2024 and PHX from 2025. Same franchise
    # throughout; the feed simply changed how it writes it. Building this
    # table from the 2025 game log alone missed it, and the cost was 40 of
    # 240 games in 2024 resolving to no team -- silently, as a NULL game_id.
    "PHO": "PHX",
    # Portland Fire, 2026 expansion. PDX is the city's airport code.
    "PDX": "POR",
}

#: Franchises that existed in the feed's history but not in our `teams`
#: table. Listed rather than mapped, because none of them is the SAME
#: entity as a current team even where the franchise later relocated -- a
#: 2005 Sacramento Monarchs game is not a Las Vegas Aces game, and folding
#: them together would corrupt every historical team record.
#:
#: Ingesting seasons before 2010 therefore needs these created first. They
#: are absent, not wrong, and `to_canonical` passing them through unchanged
#: makes the game fail to resolve loudly rather than attach to the wrong
#: franchise.
HISTORICAL_ONLY: dict[str, str] = {
    "SAN": "San Antonio Silver Stars (2003-2017)",
    "SAC": "Sacramento Monarchs (1997-2009)",
    "HOU": "Houston Comets (1997-2008)",
    "DET": "Detroit Shock (1998-2009)",
    "CHA": "Charlotte Sting (1997-2006)",
    "CLE": "Cleveland Rockers (1997-2003)",
    "UTA": "Utah Starzz (1997-2002)",
    "TUL": "Tulsa Shock (2010-2015)",
    "ORL": "Orlando Miracle (1999-2002)",
    "MIA": "Miami Sol (2000-2002)",
}


def to_canonical(abbreviation: str) -> str:
    """Our abbreviation for a stats.wnba.com one.

    Unmapped input is returned unchanged: most abbreviations agree, and a
    caller looking one up will fail to find a team rather than find the
    wrong one.
    """
    return STATS_TO_CANONICAL.get(abbreviation.upper(), abbreviation.upper())


def parse_matchup(matchup: str) -> tuple[str, str] | None:
    """('CHI vs. NYL') -> (home, away) as CANONICAL abbreviations.

    The feed writes 'A vs. B' when A is home and 'A @ B' when A is away, so
    the separator carries the venue and the order alone does not.
    """
    for separator, home_first in ((" vs. ", True), (" @ ", False)):
        if separator in matchup:
            left, _, right = matchup.partition(separator)
            first, second = to_canonical(left.strip()), to_canonical(right.strip())
            return (first, second) if home_first else (second, first)
    return None
