#!/bin/zsh
# Schedule the capture PULL on this machine.
#
# scripts/deploy-capture-host.sh schedules the recording side on the
# always-on host. Nothing scheduled the retrieval side, which is how four
# days of correctly-captured data ended up sitting unread on 2026-08-03.
# This closes that half.
#
# Idempotent: re-running replaces the agent in place.
#
# Usage: scripts/install-market-sync.sh [--uninstall]
set -euo pipefail

LABEL="com.ostepan.wnba-market-sync"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
  rm -f "$PLIST_DEST"
  echo "==> removed ${LABEL}"
  exit 0
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/wnba-market-capture/logs"

echo "==> installing ${LABEL}"
sed -e "s|PLACEHOLDER_REPO|${REPO_ROOT}|g" \
    -e "s|PLACEHOLDER_HOME|${HOME}|g" \
    "${REPO_ROOT}/scripts/${LABEL}.plist" > "$PLIST_DEST"

# bootout before bootstrap so a re-run replaces rather than erroring with
# "service already loaded".
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_DEST"

echo "==> status"
launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null \
  | grep -E 'state|last exit code|runs' || echo "agent not reporting yet"

echo
echo "Pull runs hourly. Logs: ${HOME}/wnba-market-capture/logs/sync.log"
echo "Full history sweep stays manual: scripts/backfill-prediction-markets.sh"
