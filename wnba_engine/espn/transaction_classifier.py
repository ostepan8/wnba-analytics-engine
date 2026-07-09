"""Best-effort interpretation of ESPN transaction free text -- NOT a
parser (see transactions_parser.py for the reliable structured fields).

ESPN's transactions description has no structured player field at all,
e.g.: "Waived F Liatu King.", "Released F Joyner Holmes and G Jazmine
Jones.", "Named Clare Duwelius general manager.", "Gs Marina Mabrey and
DeWanna signed a contract amendment - time-off bonus." (ESPN's own data
defect: "DeWanna" has no last name).

Two independent, deliberately narrow heuristics live here:

- classify_transaction_type: a leading-keyword scan for a coarse action
  bucket. Checked in priority order because many real descriptions combine
  two actions in one string ("Released F Amy Atwell. Signed F Amy Atwell to
  a seven-day contract.") -- only ONE type is ever returned, picked by
  priority, not by which action is "most important" in any semantic sense.
  Falls back to 'front_office' for coaching/GM text with no keyword match,
  then 'other'.

- extract_raw_player_name: finds the first WNBA position token (G/F/C and
  common combinations) and takes up to the next 3 capitalized words after
  it as a name, stopping at punctuation or the first non-capitalized/
  stopword token. Returns None when no position token is found at all
  (the correct outcome for a pure coaching/front-office move -- "Signed
  head coach Cheryl Reeve..." has no G/F/C token, so no player is invented).

KNOWN LIMITATIONS (by design, not bugs -- see 0020_player_transactions.sql
and the pipeline docstring): a description naming two players only ever
yields the FIRST one found; a description with two distinct actions may
have its extracted type and its extracted player refer to DIFFERENT actions
in the same string (e.g. "Waived G Bria Hartley ... Awarded F Emma Cannon
on waivers." classifies as 'claimed' via "Awarded" but extracts "Bria
Hartley", the player who was actually waived, since that name appears
first). A description with no position token before a name at all (e.g.
"Released Jaylyn Sherrod and signed her...") yields no player. None of
this is fixed here -- `description` is always stored verbatim precisely so
these gaps never lose information, only the derived columns.
"""

from __future__ import annotations

import re

_TRANSACTION_TYPES = (
    "traded",
    "waived",
    "signed",
    "re-signed",
    "released",
    "activated",
    "claimed",
    "placed_on_il",
    "recalled",
    "front_office",
    "other",
)

# Order is priority, not appearance -- see module docstring. Checked as
# case-insensitive substrings against the full description.
_KEYWORD_TYPE_ORDER: tuple[tuple[str, str], ...] = (
    ("traded", "traded"),
    ("acquired", "traded"),
    ("waived", "waived"),
    ("claimed", "claimed"),
    ("awarded", "claimed"),
    ("released", "released"),
    ("re-signed", "re-signed"),
    ("re-singed", "re-signed"),  # ESPN's own typo, observed live
    ("resigned", "re-signed"),
    ("signed", "signed"),
    ("agreed to terms", "signed"),
    ("reinstated", "activated"),
    ("activated", "activated"),
    ("set active", "activated"),
    ("cleared to return", "activated"),
    ("recalled", "recalled"),
)

_FRONT_OFFICE_KEYWORDS = (
    "general manager",
    "head coach",
    "assistant coach",
    "associate head coach",
    "president of basketball operations",
    "director of player",
    "basketball operations",
)


def classify_transaction_type(description: str) -> str:
    """Best-effort coarse action bucket for a transaction description.
    Always returns a member of _TRANSACTION_TYPES, never raises -- an
    unclassifiable description falls back to 'other', never blocks
    ingestion of the (always-preserved) raw description.
    """
    lowered = description.lower()
    for keyword, type_ in _KEYWORD_TYPE_ORDER:
        if keyword in lowered:
            return type_
    if "placed" in lowered and ("injury list" in lowered or "injured list" in lowered):
        return "placed_on_il"
    if any(keyword in lowered for keyword in _FRONT_OFFICE_KEYWORDS):
        return "front_office"
    return "other"


# WNBA position tokens as ESPN writes them ahead of a player name -- plural
# forms (Gs/Fs/Cs) for multi-player descriptions, and the combo forms
# ("G/F", etc) for a player listed as eligible at two positions. Longer/
# more specific alternatives are listed before their prefixes (e.g. "Gs"
# before "G") since regex alternation tries each option in order at a given
# starting position, not longest-match-wins.
_POSITION_TOKEN = re.compile(r"\b(?:Gs|Fs|Cs|G/F|F/C|G/C|C/F|C/G|F/G|G|F|C)\b")

# Runs of non-space characters (a "word"), OR a lone '.'/',' -- captured as
# their own token so sentence/list boundaries reliably terminate name
# extraction even though '.'/',' are excluded from the word alternative.
_TOKEN = re.compile(r"[^\s.,]+|[.,]")

# Words that terminate name extraction even if capitalized (defensive --
# real ESPN text almost always keeps these lowercase mid-sentence, so the
# isupper() check below already stops on most of them; this is a backstop).
_STOP_WORDS = frozenset({"and", "to", "from", "off", "on", "in", "who", "as", "for", "with"})

_MAX_NAME_WORDS = 3
_MIN_NAME_WORDS = 2


def extract_raw_player_name(description: str) -> str | None:
    """Best-effort single player name from a transaction description, or
    None when no WNBA position token precedes a name (correct for
    coaching/front-office/unparseable text -- see module docstring).
    """
    position_match = _POSITION_TOKEN.search(description)
    if position_match is None:
        return None

    rest = description[position_match.end() :]
    name_words: list[str] = []
    for token in _TOKEN.findall(rest):
        if token in (".", ","):
            break
        if token.lower() in _STOP_WORDS:
            break
        if not token[0].isupper():
            break
        name_words.append(token)
        if len(name_words) == _MAX_NAME_WORDS:
            break

    if len(name_words) < _MIN_NAME_WORDS:
        return None
    return " ".join(name_words)
