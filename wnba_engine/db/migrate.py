"""Applies pending SQL migrations from db/migrations/ in filename order."""

from __future__ import annotations

from pathlib import Path

from wnba_engine.db.pool import Database

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "db" / "migrations"

_CREATE_VERSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_SELECT_APPLIED_SQL = "SELECT version FROM schema_versions"

_RECORD_APPLIED_SQL = "INSERT INTO schema_versions (version) VALUES (%s)"


def run_migrations(db: Database, *, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    applied: list[str] = []
    with db.connection() as conn:
        conn.execute(_CREATE_VERSIONS_TABLE_SQL)
        conn.commit()

        already_applied = {row[0] for row in conn.execute(_SELECT_APPLIED_SQL).fetchall()}

        for migration_file in sorted(migrations_dir.glob("*.sql")):
            version = migration_file.stem
            if version in already_applied:
                continue
            sql = migration_file.read_text()
            # Apply + record atomically so a crash can't leave a migration
            # applied but untracked (which would re-apply it next run).
            conn.execute(sql)
            conn.execute(_RECORD_APPLIED_SQL, (version,))
            conn.commit()
            applied.append(version)

    return applied
