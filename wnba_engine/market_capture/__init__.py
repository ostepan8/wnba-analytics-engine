"""Raw prediction-market payload capture, recorded off-box and replayed
here.

WHY THIS EXISTS. Kalshi and Polymarket prices are rolling-window: the API
serves what is true now and there is no historical endpoint, so an
observation not recorded at the time is gone permanently. A laptop that
sleeps, or a Postgres that falls over, loses that data forever -- which
is exactly what happened over 2026-07-16..29, costing two thirds of every
prediction-market price ever collected.

The fix is to record on an always-on machine (a Mac Studio, over
Tailscale) and load here. What gets recorded is the RAW PROVIDER PAYLOAD,
not canonical rows, for one decisive reason: `games.id` and `players.id`
are generated per-database. A `market_price_snapshots` row written on
another machine carries that machine's `game_id`, which points at a
different game here. Any cross-machine transfer of canonical rows would
have to re-resolve those ids on arrival anyway -- so the remote side
should never produce them. It captures JSON; this side resolves.

Consequences, all deliberate:

- The capture host needs no database, no repo, no `uv`, and no secrets
  (both APIs are public and unauthenticated). It runs one stdlib-only
  script -- see `capture.py` in this package, which is deployed there
  verbatim.
- Captures are ground truth and re-ingestible. If a parser improves, the
  whole archive can be replayed through it; nothing is lost to a bug that
  existed at capture time.
- Replay reuses the EXACT ingest pipelines a live snapshot uses, via
  clients that serve recorded pages instead of HTTP (see `replay.py`).
  There is no second ingest path to keep in sync.

FILE FORMAT (v1). One gzipped JSON file per provider per capture run,
named `<provider>/<ISO8601 basic UTC>.json.gz`, e.g.
`kalshi/20260729T183000Z.json.gz`. Contents:

    {
      "schema_version": 1,
      "provider": "kalshi" | "polymarket",
      "captured_at": "2026-07-29T18:30:00Z",   # RFC3339 UTC
      "pages": [ ... provider-specific, see replay.py ... ]
    }

`captured_at` is authoritative and is what lands in
`market_price_snapshots.captured_at` -- never the ingest wall-clock. A
file recorded three days ago must not claim to have been observed today.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

PROVIDER_KALSHI = "kalshi"
PROVIDER_POLYMARKET = "polymarket"
# ESPN's league-wide injury report is captured here for exactly the same
# reason the market feeds are: it is current-state-only with no
# historical endpoint (see db/migrations/0005_injury_reports.sql), so a
# day not recorded is a day lost. The Wayback backfill recovers only what
# archive.org happened to crawl -- 11 snapshots across three months of
# the 2026 season, versus 48/day here.
PROVIDER_ESPN_INJURIES = "espn-injuries"

# Basic-format ISO8601 so the name is filesystem-safe and sorts
# chronologically as a plain string.
CAPTURE_FILENAME_FORMAT = "%Y%m%dT%H%M%SZ"
CAPTURE_SUFFIX = ".json.gz"
