"""Internet Archive Wayback Machine client, scoped to one page: ESPN's WNBA
injuries page. This is the ONLY way to get real point-in-time historical
injury status -- ESPN's live /injuries API is current-state only (verified
directly: querying it against a years-old game still returns today's data).
Every Wayback snapshot is a genuine "this was true on this date" record.

Two calls: the CDX API lists snapshot timestamps for a date range, and the
id_ raw-content endpoint fetches one snapshot's actual archived HTML
(unmodified, no Wayback toolbar injected).
"""

from __future__ import annotations

from datetime import date

from wnba_engine.config import Settings
from wnba_engine.http_client import RETRYABLE_STATUS_CODES, JsonHttpClient

PROVIDER = "espn-wayback"
TARGET_URL = "https://www.espn.com/wnba/injuries"

# archive.org's raw snapshot endpoint has been observed, on real backfill
# runs, to intermittently 403 on a snapshot the CDX index itself confirms
# was captured successfully (statuscode 200) -- a serving-layer hiccup, not
# the permanent per-day 403 baked into the CDX record when ESPN blocked the
# original crawl. Retrying that specific case is worthwhile; see
# JsonHttpClient's retryable_status_codes docstring for why this isn't the
# global default.
_RETRYABLE_STATUS_CODES = RETRYABLE_STATUS_CODES | {403}


class WaybackClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.wayback_base_url
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.wayback_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.wayback_min_request_interval_seconds,
            retryable_status_codes=_RETRYABLE_STATUS_CODES,
        )

    def fetch_snapshot_timestamps(self, since: date, until: date) -> object:
        """CDX API: every successful-capture timestamp in [since, until],
        not collapsed to one per day.

        filter=statuscode:200 excludes captures we already know are dead
        (ESPN blocking the crawler at that exact moment). Deliberately NOT
        collapsed to one-per-day here: even a CDX-confirmed 200 can fail at
        fetch time for reasons the CDX status doesn't capture -- observed
        live, a "revisit" record pointing to a differently-timestamped
        capture that was failing on archive.org's own storage backend. The
        pipeline groups these by day and tries same-day alternates in order
        until one actually works, rather than giving up on the day after
        one candidate fails.
        """
        return self._http.get_json(
            "cdx/search/cdx",
            params={
                "url": "espn.com/wnba/injuries",
                "output": "json",
                "from": since.strftime("%Y%m%d"),
                "to": until.strftime("%Y%m%d"),
                "filter": "statuscode:200",
                "limit": 100_000,
            },
        )

    def fetch_snapshot_html(self, timestamp: str) -> str:
        """Raw archived HTML for one CDX-listed timestamp (format YYYYMMDDhhmmss).

        Passes a full absolute URL rather than a base_url-relative path:
        base_url.join() mangles the embedded "https://" in a relative path
        into "https:/" (single slash), which archive.org does not accept.
        """
        return self._http.get_text(f"{self._base_url}/web/{timestamp}id_/{TARGET_URL}")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WaybackClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
