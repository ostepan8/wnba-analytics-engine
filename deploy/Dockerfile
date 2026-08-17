# One image, three roles: the CLI, the scheduler, and the read API all run from
# this same build. They share a codebase and a database schema, so shipping them
# as one artifact means a migration and the code that depends on it can never be
# deployed a version apart.
#
# Built on the node that runs it. nephos does not distribute images
# (`nephos guide deploy`), so `image: localhost/...` must already exist locally
# -- see deploy/build.sh.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# uv defaults to a copy-on-write link into its cache, which fails across the
# layer boundary and falls back to copying with a warning on every build.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first, from the lockfile alone. This layer is keyed on
# pyproject.toml + uv.lock, so editing engine code -- the common case -- reuses
# the cached install instead of re-resolving 121 packages.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra api

COPY . .
RUN uv sync --frozen --no-dev --extra api

# The venv's bin directory, so `wnba-engine` and `python` resolve without `uv
# run`. The scheduler spawns these as subprocesses (wnba_engine/scheduler/
# runner.py) and passing them through `uv run` would add a lock check and a
# process layer to every single fire.
ENV PATH="/app/.venv/bin:${PATH}"

# Where raw market captures are written and read from. Mounted as a volume by
# the scheduler's manifest: these files are the durable record of feeds with no
# historical endpoint, and must outlive any container.
ENV WNBA_CAPTURE_ROOT=/data/captures
VOLUME ["/data/captures"]

# Deliberately no CMD. Each manifest sets its own `command:` -- the scheduler
# runs `python -m wnba_engine.scheduler`, the API runs uvicorn, and a one-off
# backfill runs a `wnba-engine` subcommand. A default here would only ever be
# wrong for two of the three.
