"""Crosswalk (provider_entity_map) integrity checks. No FK enforces these
at the DB level -- internal_id is polymorphic (points at teams, players,
or games depending on entity_type), so Postgres can't reference it
directly; these checks are the substitute.
"""

from __future__ import annotations

from psycopg import Connection

from wnba_engine.models.validation import CheckResult
from wnba_engine.validation._shared import build_check_result

_ORPHANED_ENTRIES_SQL = """
SELECT pem.provider, pem.entity_type, pem.external_id, pem.internal_id
FROM provider_entity_map pem
WHERE (pem.entity_type = 'team'
       AND NOT EXISTS (SELECT 1 FROM teams t WHERE t.id = pem.internal_id))
   OR (pem.entity_type = 'player'
       AND NOT EXISTS (SELECT 1 FROM players p WHERE p.id = pem.internal_id))
   OR (pem.entity_type = 'game'
       AND NOT EXISTS (SELECT 1 FROM games g WHERE g.id = pem.internal_id))
"""


def check_orphaned_crosswalk_entries(conn: Connection) -> CheckResult:
    """Every crosswalk mapping's internal_id must reference a real
    canonical row. A dangling one means the canonical row was deleted (no
    code path does this today) or the mapping was written with a bad id.
    """
    rows = conn.execute(_ORPHANED_ENTRIES_SQL).fetchall()
    return build_check_result(
        name="orphaned_crosswalk_entries",
        description="provider_entity_map.internal_id references a real teams/players/games row",
        rows=rows,
        formatter=lambda r: f"{r[0]}/{r[1]} external_id={r[2]} -> missing internal_id={r[3]}",
    )


_DUPLICATE_MAPPINGS_SQL = """
SELECT provider, entity_type, internal_id,
       array_agg(external_id ORDER BY external_id) AS external_ids
FROM provider_entity_map
GROUP BY provider, entity_type, internal_id
HAVING count(*) > 1
"""


def check_duplicate_crosswalk_mappings(conn: Connection) -> CheckResult:
    """One provider's entity_type should map exactly one external_id onto
    a given canonical row. More than one usually means two distinct raw
    entities (e.g. two different players who happen to share a name) got
    merged into the same canonical row by resolve_or_create_player_by_name's
    name-matching fallback.

    Known, verified-benign exception: balldontlie itself sometimes issues
    a DIFFERENT player id for the same real person across its own separate
    endpoints (advanced-stats vs. traditional-box-score, observed live for
    a handful of players) -- not a provider we control, so this is a real
    provider-side quirk, not a crosswalk bug. When investigating a flagged
    balldontlie/player entry, check whether both external_ids consistently
    appear under the SAME team_id in player_advanced_stats /
    player_game_stats -- that's strong evidence it's the same person, not
    a bad merge (verified for 3 real cases this way before concluding they
    were fine, not "fixed" away here since silently suppressing a
    legitimate-looking pattern risks hiding a genuinely bad future merge).
    """
    rows = conn.execute(_DUPLICATE_MAPPINGS_SQL).fetchall()
    return build_check_result(
        name="duplicate_crosswalk_mappings",
        description="a provider's external_ids map 1:1 onto canonical rows, never many:1",
        rows=rows,
        formatter=lambda r: f"{r[0]}/{r[1]} internal_id={r[2]} <- external_ids={r[3]}",
    )
