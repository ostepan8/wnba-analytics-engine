#!/bin/zsh
# Pull raw market captures from the capture host and load them.
#
# rsync over SSH rather than an HTTP service on the host: there is no
# daemon to keep alive, no port to expose, and rsync already handles
# resume, partial transfers, and "only what's new" correctly.
#
# Both halves are idempotent, so running this on any cadence (or twice by
# accident) is safe:
#   - rsync copies only files not already present locally.
#   - ingest skips files older than what's stored, and
#     UNIQUE(provider, market_external_id, captured_at) rejects the rest.
#
# Usage: scripts/sync-market-captures.sh [ssh-host] [local-root]
set -euo pipefail

HOST="${1:-mac-studio}"
LOCAL_ROOT="${2:-$HOME/wnba-market-capture}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

REMOTE_HOME="$(ssh "$HOST" 'echo $HOME')"
REMOTE_DATA="${REMOTE_HOME}/wnba-market-capture/data/"

mkdir -p "$LOCAL_ROOT"

echo "==> pulling captures from ${HOST}"
# --ignore-existing: captures are immutable once written, so never re-copy.
# --exclude '.*.partial': capture.py writes to a temp name and renames, so
#   a file being written right now must not be transferred half-formed.
rsync -az --ignore-existing --exclude '.*.partial' \
    "${HOST}:${REMOTE_DATA}" "${LOCAL_ROOT}/"

echo "==> local capture inventory"
for provider in kalshi polymarket espn-injuries; do
  count=$(ls "${LOCAL_ROOT}/${provider}"/*.json.gz 2>/dev/null | wc -l | tr -d ' ')
  echo "    ${provider}: ${count} file(s)"
done

echo "==> ingesting"
cd "$REPO_ROOT"
uv run wnba-engine ingest-market-captures --dir "$LOCAL_ROOT"
