"""Curated player-name aliases: a name a provider actually uses -> the
canonical `players.full_name`.

Every entry here is an EXACT, individually-verified mapping, not a fuzzy
rule. That distinction is the whole design: heuristic matching on a
sportsbook feed is dangerous because real WNBA rosters contain genuinely
similar names -- "Cheyenne Parker" vs "Candace Parker", "Napheesa
Collier" vs "Charli Collier", a dozen Williamses -- and mis-attributing a
prop to the wrong player is a silent, plausible-looking error that no
downstream check would catch.

Two things land here, both found by running a real multi-season backfill
and reading what failed to resolve:

- **Name changes.** Players marry, hyphenate, un-hyphenate, or rebrand
  mid-career, and historical odds keep the name that was current when the
  line was posted. The canonical row holds today's name.
- **Provider misspellings.** Some books consistently misspell a name
  ("Napeesha Collier", "Natisha Heideman"). Verified against the roster
  before being added -- a misspelling only earns an entry when exactly
  one real player plausibly matches.

Deliberately NOT here: `"Collier N."`, an abbreviated form appearing in
some 2023 payloads. Both Napheesa Collier and Charli Collier are real
players in this database, so that string is genuinely ambiguous and is
left unresolved rather than guessed.

Applied by entity_repo.find_player_by_name for every caller, since an
exact curated mapping cannot manufacture a false match the way the
opt-in reversed-order heuristic could. That also fixes the two
season_awards misses DATA_INVENTORY.md documents, which were this same
"Skylar Diggins" / "Skylar Diggins-Smith" problem.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# provider's spelling -> canonical players.full_name
NAME_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        # --- name changes (canonical row holds the current name) ---
        # Dropped "-Smith" during her career; 2023-2025 odds still say it.
        # This is also the documented season_awards miss.
        "skylar diggins-smith": "Skylar Diggins",
        # Married and hyphenated in 2024; earlier odds say "Parker".
        "cheyenne parker": "Cheyenne Parker-Tyus",
        # Married and hyphenated; earlier odds say "Laney".
        "betnijah laney": "Betnijah Laney-Hamilton",
        # Rebranded from "Asia Durr" to "AD Durr". Unambiguous: she is the
        # only Durr in the players table.
        "asia durr": "AD Durr",
        # --- provider misspellings ---
        "napeesha collier": "Napheesa Collier",  # transposed vowels
        "alisha gray": "Allisha Gray",  # dropped an 'l'
        "natisha heideman": "Natisha Hiedeman",  # transposed 'ie'
    }
)


def canonical_name(name: str) -> str | None:
    """The canonical full_name for a provider's spelling, or None.

    Case- and whitespace-insensitive on the lookup side so callers don't
    have to normalize first; the returned value is the exact canonical
    spelling to match against players.full_name.
    """
    return NAME_ALIASES.get(name.strip().casefold())
