#!/usr/bin/env bash
# Build the engine image on the node that will run it.
#
# nephos deploys manifests, not images (`nephos guide deploy`), so
# `image: localhost/wnba-engine:latest` has to already exist on the target
# node. Run this over SSH on that node before `nephos up`.
#
# Idempotent, and cheap on a rebuild: the dependency layer is keyed on
# pyproject.toml + uv.lock, so a code-only change reuses it.
#
# Usage:  deploy/build.sh [tag]     (default: localhost/wnba-engine:latest)
set -euo pipefail

TAG="${1:-localhost/wnba-engine:latest}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> building ${TAG} from ${REPO_ROOT}"
# --pull=newer, not --pull: refresh the base image when upstream moved, but
# still build offline against the cached one if the registry is unreachable.
# A home connection that drops must not break a redeploy.
podman build \
    --pull=newer \
    --file "${REPO_ROOT}/deploy/Dockerfile" \
    --tag "${TAG}" \
    "${REPO_ROOT}"

echo "==> built"
podman images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -F "${TAG%%:*}" || true

# Fail loudly here rather than at deploy time. A broken entry point surfaces as
# a container that restarts forever, which is far harder to read than this.
echo "==> smoke test"
podman run --rm "${TAG}" wnba-engine --help >/dev/null
podman run --rm "${TAG}" python -c 'import wnba_engine.scheduler.runner' >/dev/null
echo "==> ok"
