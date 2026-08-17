"""Choosing which known player a loose name refers to.

Pure: the caller supplies candidates and a function that talks to a model. This
module builds the question, reads the answer, and refuses anything it cannot
verify. No network, no database.

The design exists to make a wrong answer impossible to express, because a wrong
answer here is the failure mode this project has already had: 43% of prop rows
once carried the wrong player, repaired in migration 0033. So:

**The model picks an index, never a name.** It is shown a numbered short list
and must reply with one number. It cannot invent a player, cannot return a
near-miss spelling, and cannot return somebody who was not offered. Anything
that is not a valid index on the list is treated as no answer at all.

**Declining is a first-class answer.** `0` means "none of these". A model forced
to choose from a list will always choose something, and a confident wrong pick
is worse than the missing row we would have had anyway.

**It never runs first.** Deterministic matching -- exact, diacritic-folded,
reversed order -- decides every name it can. This is the fallback for the ones
that would otherwise be dropped, so its worst case is the status quo.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

# Ask for one token; a chatty model that explains itself is a parse failure.
MAX_ANSWER_TOKENS = 8

# More than this and the list stops being a short list. Trigram ranking already
# puts the right player near the top, so a long tail only adds ways to be wrong.
MAX_CANDIDATES = 8

_LEADING_INT = re.compile(r"-?\d+")

PROMPT = """You match a player name from a sports document to a known player.

The name as written: "{name}"{context}

Known players:
{options}

Reply with ONLY the number of the matching player.
Reply with 0 if none of them is the same person.
Do not explain."""


@dataclass(frozen=True, slots=True)
class Candidate:
    player_id: int
    full_name: str
    team_abbreviation: str | None = None
    # Trigram similarity to the raw name, when the caller ranked them. Lets a
    # confident, unambiguous match skip the model entirely.
    score: float | None = None

    def label(self) -> str:
        if self.team_abbreviation:
            return f"{self.full_name} ({self.team_abbreviation})"
        return self.full_name


@dataclass(frozen=True, slots=True)
class Resolution:
    """What was decided, and enough to audit it later."""

    player_id: int | None
    candidates: tuple[Candidate, ...]
    raw_reply: str | None = None
    declined: bool = False


def build_prompt(name: str, candidates: Sequence[Candidate], *, context: str = "") -> str:
    """The question, with candidates numbered from 1."""
    options = "\n".join(
        f"{index}. {candidate.label()}" for index, candidate in enumerate(candidates, start=1)
    )
    suffix = f"\nSeen alongside: {context}" if context else ""
    return PROMPT.format(name=name, context=suffix, options=options)


def parse_choice(reply: str | None, candidate_count: int) -> int | None:
    """The chosen 1-based index, 0 for "none", or None if unusable.

    Deliberately strict about range. A model that answers "9" against a list of
    five has not chosen anybody, and mapping that onto a real player by
    clamping or wrapping is precisely how a confident wrong row gets written.
    """
    if reply is None:
        return None
    match = _LEADING_INT.search(reply)
    if match is None:
        return None
    value = int(match.group(0))
    if value < 0 or value > candidate_count:
        return None
    return value


def resolve(
    name: str,
    candidates: Sequence[Candidate],
    ask: Callable[[str], str | None],
    *,
    context: str = "",
    max_candidates: int = MAX_CANDIDATES,
) -> Resolution:
    """Pick the candidate `name` refers to, or decline.

    `ask` is any callable taking a prompt and returning the model's text. It may
    raise or return None -- an unreachable model resolves to nothing, which is
    exactly the outcome the caller had before this existed.
    """
    shortlist = tuple(candidates[:max_candidates])
    if not shortlist:
        return Resolution(player_id=None, candidates=())

    # One candidate is still a question, not a conclusion. The deterministic
    # matcher already failed on this name, so "the only vaguely similar player"
    # is a coincidence as often as a match.
    try:
        reply = ask(build_prompt(name, shortlist, context=context))
    except Exception:
        return Resolution(player_id=None, candidates=shortlist)

    choice = parse_choice(reply, len(shortlist))
    if choice is None:
        return Resolution(player_id=None, candidates=shortlist, raw_reply=reply)
    if choice == 0:
        return Resolution(player_id=None, candidates=shortlist, raw_reply=reply, declined=True)
    return Resolution(
        player_id=shortlist[choice - 1].player_id, candidates=shortlist, raw_reply=reply
    )


# A trigram match at or above this, with clear daylight to the runner-up, is
# taken without asking a model. "Parker- Tyus, Cheyenne" scores 1.000 against
# "Cheyenne Parker-Tyus" -- the trigram set is identical, only the word order
# and punctuation differ -- so the expensive path would be pure ceremony.
CONFIDENT_SCORE = 0.75

# ...and it must be clearly ahead of the next candidate. Two players scoring
# 0.8 apiece is exactly the ambiguity the model is for.
CONFIDENT_MARGIN = 0.15


def confident_match(candidates: Sequence[Candidate]) -> Candidate | None:
    """The one obviously-right candidate, or None if it is a judgement call."""
    ranked = [c for c in candidates if c.score is not None]
    if not ranked or ranked[0].score is None or ranked[0].score < CONFIDENT_SCORE:
        return None
    runner_up = ranked[1].score if len(ranked) > 1 and ranked[1].score is not None else 0.0
    if ranked[0].score - runner_up < CONFIDENT_MARGIN:
        return None
    return ranked[0]


def candidates_as_json(candidates: Sequence[Candidate]) -> list[dict[str, Any]]:
    """What was on the table, for the decision log."""
    return [
        {
            "player_id": candidate.player_id,
            "full_name": candidate.full_name,
            "team": candidate.team_abbreviation,
            "score": candidate.score,
        }
        for candidate in candidates
    ]
