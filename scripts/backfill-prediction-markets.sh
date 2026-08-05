#!/bin/zsh
# Backfill all recoverable prediction-market history, both venues at once.
#
# Polymarket and Kalshi are independent hosts with independent rate limits and
# no shared state, so running them concurrently roughly halves wall clock. They
# do share a Postgres connection pool, but each writes its own table and
# commits per market, so there is no lock contention worth serialising for.
#
# Safe to re-run on any cadence. Both halves are idempotent:
#   - polymarket_trades is keyed on the on-chain fill identity
#   - kalshi_candlesticks is keyed on (market, resolution, bar end)
# Neither key includes captured_at, so a second run inserts 0 rather than
# duplicating the first (db/migrations/0025_prediction_market_history.sql).
#
# Usage: scripts/backfill-prediction-markets.sh [--period 1|60|1440] [--full]
#   --period  Kalshi bar size, default 60. 1-minute is capped at a ~3-day
#             request window, so a full sweep costs ~50x the requests.
#   --full    Re-fetch Polymarket markets that already have stored fills.
#             Needed to pick up new trades on markets still open; without it
#             those markets are skipped, which is what makes a re-run cheap.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PERIOD=60
RESUME_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --period) PERIOD="$2"; shift 2 ;;
    --full)   RESUME_FLAG="--no-resume"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"
LOG_DIR="${TMPDIR:-/tmp}/wnba-pm-backfill"
mkdir -p "$LOG_DIR"
POLY_LOG="${LOG_DIR}/polymarket.log"
KALSHI_LOG="${LOG_DIR}/kalshi.log"

echo "==> starting both backfills in parallel (logs in ${LOG_DIR})"

# Each half writes to its own log rather than interleaving on the terminal:
# both emit per-market progress, and interleaved output makes a failure in
# one impossible to attribute.
uv run wnba-engine backfill-polymarket-trades ${RESUME_FLAG} >"$POLY_LOG" 2>&1 &
POLY_PID=$!
uv run wnba-engine backfill-kalshi-candles --period "$PERIOD" >"$KALSHI_LOG" 2>&1 &
KALSHI_PID=$!

# Collect both exit codes before failing on either, so one venue erroring
# does not hide whether the other finished. `set -e` would otherwise abort
# at the first non-zero wait.
POLY_STATUS=0
KALSHI_STATUS=0
wait "$POLY_PID" || POLY_STATUS=$?
wait "$KALSHI_PID" || KALSHI_STATUS=$?

echo "==> polymarket (exit ${POLY_STATUS})"
tail -n 2 "$POLY_LOG"
echo "==> kalshi (exit ${KALSHI_STATUS})"
tail -n 2 "$KALSHI_LOG"

if [[ $POLY_STATUS -ne 0 || $KALSHI_STATUS -ne 0 ]]; then
  echo "==> at least one backfill failed; full logs in ${LOG_DIR}" >&2
  exit 1
fi

# Matchers improve over time and ON CONFLICT DO NOTHING cannot repair a row
# already stored, so a relink pass belongs at the end of every backfill --
# see wnba_engine/pipeline/market_game_relink.py for the 18,042-row incident
# that made this non-optional.
echo "==> relinking any newly resolvable game ids"
uv run wnba-engine relink-market-games

echo "==> done"
