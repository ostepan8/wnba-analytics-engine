"""wnba-cli -- an agent-facing CLI wrapper around the read-only wnba-api.

One subcommand per API route (see wnba_engine/api/routes/). Not to be
confused with wnba_engine.cli (the ingest/ops CLI, which talks to Postgres
directly) -- this package only ever speaks HTTP to the public API, and has
no dependency on wnba_engine at all.
"""
