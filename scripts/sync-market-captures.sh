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

# WNBA_REPO_ROOT lets this run from a copy installed outside the repo.
#
# The launchd agent cannot execute this file in place. The repo lives under
# ~/Desktop, which macOS protects with TCC, and a launchd-spawned /bin/zsh
# is allowed to stat a file there but NOT to read it -- so `zsh
# .../sync-market-captures.sh` exits 127 with "can't open input file" for a
# script that is present, readable and executable from a terminal. Verified
# with a probe agent on 2026-08-05: `ls` succeeded, `cat` was denied.
#
# So install-market-sync.sh copies this script to ~/wnba-market-capture/bin
# (not TCC-protected) and passes the repo path in this variable. Reads
# INSIDE the repo still work, because those are done by `uv`/python rather
# than by the launchd shell -- which is why the odds-focused agent, whose
# plist only ever runs `cd REPO && uv run ...`, was unaffected.
REPO_ROOT="${WNBA_REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

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
