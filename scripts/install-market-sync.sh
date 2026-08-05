#!/bin/zsh
# Schedule the local launchd agents: the capture PULL, and the focused
# high-frequency odds capture.
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

# Two agents, both local:
#   market-sync    hourly, pulls captures off the always-on host
#   odds-focused   every 5 min, but self-gating -- see its plist
LABELS=(com.ostepan.wnba-market-sync com.ostepan.wnba-odds-focused)
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--uninstall" ]]; then
  for label in "${LABELS[@]}"; do
    launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
    rm -f "${HOME}/Library/LaunchAgents/${label}.plist"
    echo "==> removed ${label}"
  done
  exit 0
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/wnba-market-capture/logs"

for label in "${LABELS[@]}"; do
  dest="${HOME}/Library/LaunchAgents/${label}.plist"
  echo "==> installing ${label}"
  sed -e "s|PLACEHOLDER_REPO|${REPO_ROOT}|g" \
      -e "s|PLACEHOLDER_HOME|${HOME}|g" \
      "${REPO_ROOT}/scripts/${label}.plist" > "$dest"

  # bootout before bootstrap so a re-run replaces rather than erroring
  # with "service already loaded".
  launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$dest"
  launchctl print "${DOMAIN}/${label}" 2>/dev/null \
    | grep -E 'state|last exit code|runs' || echo "   (not reporting yet)"
done

echo
echo "Pull runs hourly.        logs: ${HOME}/wnba-market-capture/logs/sync.log"
echo "Focused odds every 5min. logs: ${HOME}/wnba-market-capture/logs/odds-focused.log"
echo "  (spends 0 requests unless a traded game is within 6h of tip-off)"
echo "Full history sweep stays manual: scripts/backfill-prediction-markets.sh"
