#!/usr/bin/env python3
"""Rewrite the Snapshot table in DATA_INVENTORY.md from live row counts.

The table was hand-maintained and went stale the moment a backfill landed:
on 2026-08-03 it reported 63,599 prediction-market rows while
`polymarket_trades` alone held 606,068. A stale inventory is worse than no
inventory, because it is quoted in decisions.

`count(*)`, never `pg_stat_user_tables.n_live_tup` -- DATA_INVENTORY.md's
own note explains why: those statistics reset on a crash-recovery restart
and read 0 across every table until the next ANALYZE, which looks alarming
and means nothing.

Usage: uv run python scripts/refresh-inventory-counts.py [--check]
  --check  exit 1 if the file would change, writing nothing. For CI or a
           pre-commit hook, so staleness fails loudly instead of drifting.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg

from wnba_engine.config import load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "DATA_INVENTORY.md"

_TABLE_RE = re.compile(
    r"(Real row counts as of )(\d{4}-\d{2}-\d{2})(.*?\n\n)(\| Table \| Rows.*?\n)((?:\|.*\n)+)",
    re.DOTALL,
)

#: `teams` gets an annotation because the raw number is misleading on its
#: own: the table includes national sides that appear in exhibitions and
#: are not WNBA franchises.
ANNOTATED = "teams"


def _schema_tables() -> set[str]:
    """Table names the migrations actually create.

    The inventory is a map of the SCHEMA, and `information_schema` is a map
    of whatever happens to be in the database -- which on a working machine
    includes scratch from exploratory sessions. This database held 14 such
    tables (`q_base`, `analysis_pred3`, `model_totals`, ...), several larger
    than real ones, and listing them would misrepresent the project to
    anyone reading the doc.

    Parsed from the migration files rather than maintained by hand, so a new
    table appears here the moment its migration lands.
    """
    pattern = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)", re.IGNORECASE)
    names: set[str] = set()
    for path in sorted((REPO_ROOT / "db" / "migrations").glob("*.sql")):
        names.update(pattern.findall(path.read_text()))
    return names


def _tables(conn) -> list[tuple[str, int]]:
    allowed = _schema_tables()
    names = [
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name NOT IN ('schema_migrations') ORDER BY table_name"
        ).fetchall()
        if row[0] in allowed
    ]
    counts: list[tuple[str, int]] = []
    for name in names:
        total = conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]  # noqa: S608
        if total:
            counts.append((name, int(total)))
    counts.sort(key=lambda pair: (-pair[1], pair[0]))
    return counts


def _render(counts: list[tuple[str, int]], franchises: int) -> str:
    rows: list[str] = []
    half = (len(counts) + 1) // 2
    left, right = counts[:half], counts[half:]
    for index in range(half):
        cells = []
        for pair in (left[index] if index < len(left) else None,
                     right[index] if index < len(right) else None):
            if pair is None:
                cells.append("| |")
                continue
            name, total = pair
            label = (
                f"{total} ({franchises} real franchises)"
                if name == ANNOTATED
                else f"{total:,}"
            )
            cells.append(f"| `{name}` | {label} |")
        rows.append("".join(cells).replace("||", "|"))
    return "\n".join(rows) + "\n"


def main() -> int:
    check_only = "--check" in sys.argv
    with psycopg.connect(load_settings().database_url) as conn:
        franchises = int(
            conn.execute("SELECT count(*) FROM teams WHERE is_franchise").fetchone()[0]
        )
        counts = _tables(conn)
        today = conn.execute("SELECT current_date").fetchone()[0].isoformat()

    text = INVENTORY.read_text()
    match = _TABLE_RE.search(text)
    if match is None:
        print("could not locate the Snapshot table in DATA_INVENTORY.md", file=sys.stderr)
        return 2
    updated = text[: match.start()] + (
        match.group(1) + today + match.group(3) + match.group(4) + _render(counts, franchises)
    ) + text[match.end():]

    if updated == text:
        print("DATA_INVENTORY.md snapshot is current")
        return 0
    if check_only:
        print("DATA_INVENTORY.md snapshot is STALE (run without --check to fix)")
        return 1
    INVENTORY.write_text(updated)
    print(f"rewrote {len(counts)} table counts as of {today}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
