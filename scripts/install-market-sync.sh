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
#   odds-focused   every 2 min, gated on a game being near tip -- see its plist
LABELS=(com.ostepan.wnba-market-sync com.ostepan.wnba-odds-focused)
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

# Refuse to install from a worktree.
#
# REPO_ROOT gets baked into both plists as an absolute path. Installing
# from a worktree therefore points a permanent launchd agent at a
# directory whose whole purpose is to be deleted. That happened: both
# agents were installed from --pm-backfill, which was removed on merge,
# after which odds-focused exited 78 and market-sync exited 127 on every
# fire. launchd does not complain, the logs look like ordinary skips, and
# the data loss is only visible weeks later as an absence.
#
# In a worktree these two differ; in the main checkout they are the same.
if [[ "$(git -C "$REPO_ROOT" rev-parse --git-dir 2>/dev/null)" \
   != "$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null)" ]]; then
  echo "ERROR: ${REPO_ROOT} is a git worktree." >&2
  echo "These agents outlive worktrees. Install from the main checkout:" >&2
  echo "  cd \$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir)/.. \\" >&2
  echo "    && scripts/install-market-sync.sh" >&2
  exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  for label in "${LABELS[@]}"; do
    launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
    rm -f "${HOME}/Library/LaunchAgents/${label}.plist"
    echo "==> removed ${label}"
  done
  exit 0
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/wnba-market-capture/logs" \
         "${HOME}/wnba-market-capture/bin"

# Stage the sync script outside the repo.
#
# A launchd-spawned /bin/zsh cannot READ files under ~/Desktop (TCC): it
# can stat them, so the path looks fine, but opening the script fails and
# the agent exits 127 forever. ~/wnba-market-capture is not protected.
# Refreshed on every install so the copy cannot drift from the repo.
echo "==> staging sync script outside the TCC-protected repo"
install -m 0755 "${REPO_ROOT}/scripts/sync-market-captures.sh" \
                "${HOME}/wnba-market-capture/bin/sync-market-captures.sh"

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
echo "Focused odds every 2min. logs: ${HOME}/wnba-market-capture/logs/odds-focused.log"
echo "  (spends 0 requests unless a game is within 6h of tip-off)"
echo "Full history sweep stays manual: scripts/backfill-prediction-markets.sh"
