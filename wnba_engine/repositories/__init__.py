"""Repository layer: all SQL lives here, nowhere else.

Canonical entities are upserted; market price snapshots are append-only.
Every function takes an open psycopg Connection — transaction scope is the
caller's responsibility (the pipeline commits per unit of work).
"""
