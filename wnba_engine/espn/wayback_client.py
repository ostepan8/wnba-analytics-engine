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
from wnba_engine.http_client import JsonHttpClient

PROVIDER = "espn-wayback"
TARGET_URL = "https://www.espn.com/wnba/injuries"


class WaybackClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.wayback_base_url
        self._http = JsonHttpClient(
            provider=PROVIDER,
            base_url=settings.wayback_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            min_request_interval_seconds=settings.wayback_min_request_interval_seconds,
        )

    def fetch_snapshot_timestamps(self, since: date, until: date) -> object:
        """CDX API: one snapshot timestamp per calendar day in [since, until].

        collapse=timestamp:8 keeps only the first capture per YYYYMMDD, since
        we only need one point-in-time read per day, not every intraday
        recrawl.
        """
        return self._http.get_json(
            "cdx/search/cdx",
            params={
                "url": "espn.com/wnba/injuries",
                "output": "json",
                "from": since.strftime("%Y%m%d"),
                "to": until.strftime("%Y%m%d"),
                "collapse": "timestamp:8",
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
