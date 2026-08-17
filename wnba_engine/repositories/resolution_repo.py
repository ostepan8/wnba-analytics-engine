"""Candidate generation and the decision log for name -> player resolution.

See db/migrations/0034_name_resolution.sql for why this exists: several sources
name a player and give no id, and getting that wrong has already corrupted a
fact table once.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from wnba_engine.llm.name_resolver import Candidate

# Trigram similarity against every known player.
#
# This is the step that makes an LLM fallback usable at all: without it the
# model would be choosing from a thousand names, and with it the right player is
# almost always in the top few. "Parker- Tyus, Cheyenne" -- which exact,
# diacritic-folded and reversed-order matching all miss, because the PDF text
# layer split the surname -- ranks correctly here.
_SIMILAR_PLAYERS = """
WITH ranked AS (
    SELECT p.id, p.full_name, similarity(p.full_name, %(name)s) AS score
      FROM players p
     WHERE similarity(p.full_name, %(name)s) >= %(threshold)s
     ORDER BY score DESC, p.full_name
     LIMIT %(limit)s
)
SELECT r.id, r.full_name, t.abbreviation, r.score
  FROM ranked r
  -- players carries no team, so the side a candidate plays for comes from the
  -- last game she appeared in. Worth the join: two similar names on different
  -- teams are trivially separable once the team is shown, and unlabelled they
  -- are exactly the case that gets decided wrongly.
  LEFT JOIN LATERAL (
      SELECT s.team_id
        FROM player_game_stats s
        JOIN games g ON g.id = s.game_id
       WHERE s.player_id = r.id
       ORDER BY g.start_time DESC
       LIMIT 1
  ) last_team ON TRUE
  LEFT JOIN teams t ON t.id = last_team.team_id
 ORDER BY r.score DESC, r.full_name
"""

_LOOKUP = """
SELECT player_id, method FROM player_name_resolutions
 WHERE source = %(source)s AND raw_name = %(raw_name)s AND context = %(context)s
"""

_RECORD = """
INSERT INTO player_name_resolutions
       (raw_name, context, source, player_id, method, model, candidates)
VALUES (%(raw_name)s, %(context)s, %(source)s, %(player_id)s, %(method)s,
        %(model)s, %(candidates)s)
ON CONFLICT (source, raw_name, context) DO UPDATE
   SET player_id = EXCLUDED.player_id,
       method    = EXCLUDED.method,
       model     = EXCLUDED.model,
       candidates = EXCLUDED.candidates
"""


def find_similar_players(
    conn: Connection, name: str, *, threshold: float = 0.3, limit: int = 8
) -> list[Candidate]:
    """Known players whose name is trigram-similar to `name`, best first."""
    rows = conn.execute(
        _SIMILAR_PLAYERS, {"name": name, "threshold": threshold, "limit": limit}
    ).fetchall()
    return [
        Candidate(
            player_id=int(row[0]),
            full_name=str(row[1]),
            team_abbreviation=row[2],
            score=float(row[3]),
        )
        for row in rows
    ]


def cached_decision(
    conn: Connection, *, source: str, raw_name: str, context: str = ""
) -> tuple[bool, int | None]:
    """(was_decided, player_id). A decided-but-None row means "we declined".

    The boolean matters: without it a previous decline is indistinguishable
    from never having asked, and every ingest would re-ask about the same
    unmatchable name for the rest of the season.
    """
    row = conn.execute(
        _LOOKUP, {"source": source, "raw_name": raw_name, "context": context}
    ).fetchone()
    if row is None:
        return (False, None)
    return (True, None if row[0] is None else int(row[0]))


def record_decision(
    conn: Connection,
    *,
    source: str,
    raw_name: str,
    context: str = "",
    player_id: int | None,
    method: str,
    model: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> None:
    """Log how a name was resolved, so it is auditable and asked once."""
    import json

    conn.execute(
        _RECORD,
        {
            "raw_name": raw_name,
            "context": context,
            "source": source,
            "player_id": player_id,
            "method": method,
            "model": model,
            "candidates": json.dumps(candidates) if candidates is not None else None,
        },
    )
