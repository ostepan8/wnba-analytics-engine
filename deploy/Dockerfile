# One image, three roles: the CLI, the scheduler, and the read API all run from
# this same build. They share a codebase and a database schema, so shipping them
# as one artifact means a migration and the code that depends on it can never be
# deployed a version apart.
#
# Built on the node that runs it. nephos does not distribute images
# (`nephos guide deploy`), so `image: localhost/...` must already exist locally
# -- see deploy/build.sh.

# --- stage 1: build the frontend ------------------------------------------
#
# Node exists only here. The runtime image gets the compiled bundle and no
# JavaScript toolchain, which keeps ~200 MB of node_modules out of production
# and off the attack surface.
FROM docker.io/library/node:22-bookworm-slim AS frontend

WORKDIR /build

# Lockfile first: this layer is keyed on the dependency manifest, so editing a
# component reuses the installed modules instead of resolving them again.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# tsc runs as part of `npm run build`, so a type error fails the image build
# rather than shipping a bundle that throws in the browser.
#
# --outDir overrides vite.config.ts, which writes into the Python package for
# local development. That relative path escapes this stage's build context, so
# the container build sends it somewhere predictable instead.
RUN npm run build -- --outDir dist --emptyOutDir


# --- stage 2: the runtime image -------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# uv defaults to a copy-on-write link into its cache, which fails across the
# layer boundary and falls back to copying with a warning on every build.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# pg_dump, for `wnba-engine backup-database`. Client package only -- the server
# is a separate container.
#
# It must be version 16, matching wnba-postgres. pg_dump refuses outright to
# dump a server newer than itself ("aborting because of server version
# mismatch"), and bookworm ships client 15, so this pulls from the PostgreSQL
# project's own apt repository rather than Debian's.
#
# No `|| apt-get install postgresql-client` fallback. An earlier version had
# one, it silently installed 15, and every backup failed at run time on a
# mismatch the fallback existed to avoid. A missing package must break the
# build, which is the one place someone is watching.
RUN apt-get update \
 && apt-get install --no-install-recommends -y ca-certificates curl gnupg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install --no-install-recommends -y postgresql-client-16 \
 && apt-get purge -y curl gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && pg_dump --version | grep -q ' 16\.'

# Dependencies first, from the lockfile alone. This layer is keyed on
# pyproject.toml + uv.lock, so editing engine code -- the common case -- reuses
# the cached install instead of re-resolving 121 packages.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra api --extra assets

COPY . .
RUN uv sync --frozen --no-dev --extra api --extra assets

# After COPY . ., so the freshly compiled bundle wins over whatever a developer
# happened to have built into the package directory locally.
COPY --from=frontend /build/dist ./wnba_engine/api/static

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
