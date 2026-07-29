#!/bin/zsh
# Deploy the market-capture collector to the always-on capture host.
#
# The host needs no repo, no uv, no database, and no credentials -- just
# python3 and this one stdlib-only script. See wnba_engine/market_capture/
# for why capture happens off-box and why it records raw payloads rather
# than canonical rows.
#
# Idempotent: re-run after editing capture.py to push the new version and
# restart the agent.
#
# Usage: scripts/deploy-capture-host.sh [ssh-host]   (default: mac-studio)
set -euo pipefail

HOST="${1:-mac-studio}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.ostepan.wnba-market-capture"

echo "==> resolving remote home on ${HOST}"
REMOTE_HOME="$(ssh "$HOST" 'echo $HOME')"
REMOTE_ROOT="${REMOTE_HOME}/wnba-market-capture"

echo "==> creating ${REMOTE_ROOT}"
ssh "$HOST" "mkdir -p '${REMOTE_ROOT}/bin' '${REMOTE_ROOT}/data' '${REMOTE_ROOT}/logs'"

echo "==> pushing capture.py"
scp -q "${REPO_ROOT}/wnba_engine/market_capture/capture.py" "${HOST}:${REMOTE_ROOT}/bin/capture.py"
ssh "$HOST" "chmod +x '${REMOTE_ROOT}/bin/capture.py'"

echo "==> installing LaunchAgent ${LABEL}"
# The plist ships with a placeholder because launchd does NOT expand ~ or
# environment variables in ProgramArguments -- absolute paths only.
sed "s|PLACEHOLDER_HOME|${REMOTE_HOME}|g" \
    "${REPO_ROOT}/scripts/${LABEL}.plist" \
  | ssh "$HOST" "cat > '${REMOTE_HOME}/Library/LaunchAgents/${LABEL}.plist'"

echo "==> reloading agent"
# bootout is expected to fail the first time (nothing loaded yet).
ssh "$HOST" "launchctl bootout gui/\$(id -u)/${LABEL} 2>/dev/null || true"
ssh "$HOST" "launchctl bootstrap gui/\$(id -u) '${REMOTE_HOME}/Library/LaunchAgents/${LABEL}.plist'"

echo "==> verifying"
ssh "$HOST" "launchctl print gui/\$(id -u)/${LABEL} 2>/dev/null | grep -E 'state|last exit code' || echo 'agent not reporting yet'"

echo ""
echo "Deployed. Captures land in ${REMOTE_ROOT}/data/{kalshi,polymarket}/"
echo "Pull them with: scripts/sync-market-captures.sh ${HOST}"
