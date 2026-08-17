"""Resolve a player NAME to a canonical player id, in strict order of trust.

    1. deterministic  -- exact, diacritic-folded, reversed order
    2. cached         -- something already decided this exact name before
    3. llm            -- pick from a trigram-ranked short list, or decline
    4. unresolved     -- the caller drops the row, as it always did

Nothing below step 1 can ever override step 1. The model is a fallback for
names that would otherwise be thrown away, so its worst case is the behaviour
this project already had, and its best case is a player who stops going
missing from the report.

Every non-deterministic decision is written to player_name_resolutions with its
candidates, which makes a bad call findable and fixable in one place rather than
silently baked into a fact table -- the thing that made the 43% prop
mis-mapping so expensive to unpick.
"""

from __future__ import annotations

import logging

from psycopg import Connection

from wnba_engine.llm.client import LlmClient
from wnba_engine.llm.name_resolver import (
    MAX_ANSWER_TOKENS,
    candidates_as_json,
    confident_match,
    resolve,
)
from wnba_engine.repositories import entity_repo, resolution_repo

logger = logging.getLogger(__name__)

# Below this trigram score a "candidate" is just another name. Offering junk
# invites the model to pick the least-bad of several wrong answers.
MIN_SIMILARITY = 0.3


def resolve_player_name(
    conn: Connection,
    raw_name: str,
    *,
    source: str,
    context: str = "",
    llm: LlmClient | None = None,
) -> int | None:
    """The player this name refers to, or None if it cannot be established."""
    # 1. Deterministic. Always first, never second-guessed.
    player_id = entity_repo.find_player_by_name(conn, raw_name, allow_reversed=True)
    if player_id is not None:
        return player_id

    # 2. Already decided once. Includes a previous decline, so an unmatchable
    #    name is not re-litigated on every two-hourly ingest.
    decided, cached = resolution_repo.cached_decision(
        conn, source=source, raw_name=raw_name, context=context
    )
    if decided:
        return cached

    candidates = resolution_repo.find_similar_players(conn, raw_name, threshold=MIN_SIMILARITY)
    if not candidates:
        return None

    # 3. An unambiguous trigram match needs no model. This catches the common
    #    shape -- same name, mangled punctuation or word order -- deterministically
    #    and for free, leaving the model only the genuinely ambiguous names.
    obvious = confident_match(candidates)
    if obvious is not None:
        resolution_repo.record_decision(
            conn,
            source=source,
            raw_name=raw_name,
            context=context,
            player_id=obvious.player_id,
            method="trigram",
            candidates=candidates_as_json(candidates),
        )
        return obvious.player_id

    if llm is None:
        return None

    # 4. Ask, from a ranked short list, with declining allowed.

    resolution = resolve(
        raw_name,
        candidates,
        lambda prompt: llm.complete(prompt, max_tokens=MAX_ANSWER_TOKENS),
        context=context,
    )

    # A model that was unreachable is NOT a decision -- recording it would cache
    # "unresolved" for a name that might resolve fine once the box wakes up.
    if resolution.raw_reply is None:
        return None

    resolution_repo.record_decision(
        conn,
        source=source,
        raw_name=raw_name,
        context=context,
        player_id=resolution.player_id,
        method="llm",
        model=llm.model,
        candidates=candidates_as_json(resolution.candidates),
    )
    if resolution.player_id is not None:
        logger.info(
            "llm resolved %r -> player_id=%s (source=%s)",
            raw_name,
            resolution.player_id,
            source,
        )
    return resolution.player_id
