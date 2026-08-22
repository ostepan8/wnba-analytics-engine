"""Fetch a league's own injury report PDF.

The league publishes to a predictable path on the NBA CDN:

    .../referee/<league>_injury/Injury-Report_<YYYY-MM-DD>_<HH>_<MM><AM|PM>.pdf

but there is no index and no "latest" alias, and a new file appears roughly
hourly through the afternoon as teams file. So finding the current report means
probing today's candidate hours newest-first and taking the first that exists.
That is a dozen HEAD requests against a static CDN, unmetered and free -- the
same reason the prediction-market feeds are polled rather than subscribed to.

Probing walks backwards from the current hour and, failing that, into
yesterday: an early-morning run must still find last night's report rather than
conclude no report exists. A team's designations stand until they refile.

Same CDN, same convention for the NBA (`nba_injury` instead of
`wnba_injury`) -- confirmed live 2026-08-22: a real filename 404s as HTTP
403 (this CDN's "no such file" response, verified by probing a garbage
WNBA filename and getting the same 403), which is exactly what the NBA
path returns right now since the NBA season hasn't started and no report
has been filed yet. The path itself is reachable; there's just nothing on
it yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# Not a Literal: callers pass this through from CLI options (click.Choice
# yields plain str) and config, so the type stays str at this boundary.
# __init__ validates against the real two values at runtime.
League = str

BASE_URL = "https://ak-static.cms.nba.com/referee/{league}_injury"

# Reports are filed on the hour and half-hour through the afternoon and
# evening. Ordered newest-first within a day.
CANDIDATE_TIMES = tuple(
    f"{hour:02d}_{minute:02d}{meridiem}"
    for meridiem in ("PM", "AM")
    for hour in (11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 12)
    for minute in (30, 0)
)

# How many days back to look before giving up.
LOOKBACK_DAYS = 2

DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True, slots=True)
class InjuryReportDocument:
    """One fetched report, with the URL it came from for traceability."""

    url: str
    content: bytes


class WnbaOfficialClient:
    """Read-only fetcher for a league's published injury report."""

    def __init__(
        self,
        *,
        league: League = "wnba",
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ):
        if league not in ("wnba", "nba"):
            raise ValueError(f"unsupported league: {league!r}")
        self._league = league
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": "wnba-analytics-engine"}
        )
        self._owns_client = client is None

    def __enter__(self) -> WnbaOfficialClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def url_for(self, day: date, stamp: str) -> str:
        base = BASE_URL.format(league=self._league)
        return f"{base}/Injury-Report_{day.isoformat()}_{stamp}.pdf"

    def fetch_latest(self, *, today: date | None = None) -> InjuryReportDocument | None:
        """The most recent published report, or None if none is findable.

        None is a real answer -- in the off-season nothing is published -- and
        is returned rather than raised so a scheduled run does not fail loudly
        every night for months.
        """
        today = today or datetime.now(UTC).date()
        for offset in range(LOOKBACK_DAYS):
            day = today - timedelta(days=offset)
            for stamp in CANDIDATE_TIMES:
                url = self.url_for(day, stamp)
                if self._exists(url):
                    logger.info("official injury report found url=%s", url)
                    return InjuryReportDocument(url=url, content=self._client.get(url).content)
        logger.warning("no official injury report found within %s days", LOOKBACK_DAYS)
        return None

    def _exists(self, url: str) -> bool:
        try:
            return self._client.head(url).status_code == 200
        except httpx.HTTPError as err:
            # A network blip on one candidate must not abort the whole search;
            # the next candidate is just as good a report.
            logger.debug("head failed url=%s err=%s", url, err)
            return False


def extract_text(content: bytes) -> str:
    """PDF bytes -> its text layer.

    Imported lazily so the dependency is only required by the code path that
    actually reads a PDF, keeping every other CLI command importable without it.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return " ".join(page.extract_text() or "" for page in reader.pages)
