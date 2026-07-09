"""Pure parser: archived ESPN /wnba/injuries page HTML -> WaybackInjuryEntry.

Archived pages embed ESPN's server-rendered data as a JSON blob in
window['__espnfitt__'] (the same pattern ESPN uses site-wide). Verified
directly, stable across snapshots from 2022 through 2026: the same
page.content.injuries[].items[] shape holds throughout.

This shape is NOT the live /injuries JSON API: no structured body-part/
side/return-date fields, just a free-text description and a short "Mon D"
date with no year, requiring inference from the snapshot's own capture
date (see _infer_reported_at).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.models.injuries import WaybackInjuryEntry
from wnba_engine.parsing import require, require_mapping, require_sequence, require_str

PROVIDER = "espn-wayback"

_EMBEDDED_JSON_RE = re.compile(r"window\['__espnfitt__'\]\s*=\s*(\{.*?\});\s*</script>", re.DOTALL)
_PLAYERCARD_ID_RE = re.compile(r"/player/_/id/(\d+)/")
_LOGO_ABBR_RE = re.compile(r"/teamlogos/wnba/\d+/([a-z]+)\.png", re.IGNORECASE)
_SHORT_DATE_RE = re.compile(r"^([A-Za-z]{3})\s+(\d{1,2})$")

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}  # fmt: skip

# A reported-date more than this many days *after* the snapshot must
# actually be from the previous year (a report from late December, read
# back from a January snapshot) -- see _infer_reported_at.
_YEAR_WRAP_THRESHOLD_DAYS = 60


def parse_wayback_injuries_page(
    html: str, *, snapshot_captured_at: datetime
) -> tuple[WaybackInjuryEntry, ...]:
    match = _EMBEDDED_JSON_RE.search(html)
    if not match:
        raise ProviderValidationError(
            PROVIDER, "could not find embedded __espnfitt__ payload in archived page"
        )
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ProviderValidationError(
            PROVIDER, f"embedded payload is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, Mapping):
        raise ProviderValidationError(PROVIDER, "embedded payload must be an object")

    page = require_mapping(data, "page", PROVIDER, "$")
    content = require_mapping(page, "content", PROVIDER, "$.page")
    team_blocks = require_sequence(content, "injuries", PROVIDER, "$.page.content")

    entries: list[WaybackInjuryEntry] = []
    for i, block in enumerate(team_blocks):
        entries.extend(_parse_team_block(block, f"injuries[{i}]", snapshot_captured_at))
    return tuple(entries)


def _parse_team_block(
    block: object, context: str, snapshot_captured_at: datetime
) -> tuple[WaybackInjuryEntry, ...]:
    if not isinstance(block, Mapping):
        raise ProviderValidationError(PROVIDER, "team block must be an object", context=context)
    logo = block.get("logo")
    abbr_match = _LOGO_ABBR_RE.search(logo) if isinstance(logo, str) else None
    if not abbr_match:
        raise ProviderValidationError(
            PROVIDER, f"could not extract team abbreviation from logo {logo!r}", context=context
        )
    abbreviation = abbr_match.group(1).upper()
    items = require_sequence(block, "items", PROVIDER, context)
    return tuple(
        _parse_item(item, abbreviation, f"{context}.items[{j}]", snapshot_captured_at)
        for j, item in enumerate(items)
    )


def _parse_item(
    item: object, abbreviation: str, context: str, snapshot_captured_at: datetime
) -> WaybackInjuryEntry:
    if not isinstance(item, Mapping):
        raise ProviderValidationError(PROVIDER, "injury item must be an object", context=context)
    player = _parse_athlete(
        require_mapping(item, "athlete", PROVIDER, context), f"{context}.athlete"
    )
    status_type_obj = require_mapping(item, "type", PROVIDER, context)
    status_type = require_str(status_type_obj, "name", PROVIDER, f"{context}.type")
    status = require_str(item, "statusDesc", PROVIDER, context)
    description = item.get("description")
    description = description if isinstance(description, str) and description.strip() else None
    return WaybackInjuryEntry(
        player=player,
        team_abbreviation=abbreviation,
        status=status,
        status_type=status_type,
        description=description,
        reported_at=_infer_reported_at(item.get("date"), description, snapshot_captured_at),
        captured_at=snapshot_captured_at,
    )


def _parse_athlete(athlete: Mapping[str, object], context: str) -> PlayerRef:
    full_name = require_str(athlete, "name", PROVIDER, context)
    href = require(athlete, "href", PROVIDER, context)
    match = _PLAYERCARD_ID_RE.search(href) if isinstance(href, str) else None
    if not match:
        raise ProviderValidationError(
            PROVIDER, f"could not extract athlete id from href {href!r}", context=context
        )
    position = athlete.get("position")
    return PlayerRef(
        external_id=match.group(1),
        full_name=full_name,
        position=position if isinstance(position, str) else None,
    )


def _infer_reported_at(
    raw_date: object, description: str | None, snapshot_captured_at: datetime
) -> datetime:
    """Best-effort report date -- neither source is fully reliable:

    - description sometimes leads with its own "Mon D: ..." date (observed
      to be the more accurate one when present -- e.g. a season-ending
      injury from September still shows "Out" in a January snapshot, with
      the *description* correctly dated September while the item's own
      "date" field was a stale/unrelated "May 1").
    - the item's own "date" field otherwise, same "Mon D" shape, no year.

    Neither field carries a year, so it's inferred from the snapshot's
    capture date: a candidate more than _YEAR_WRAP_THRESHOLD_DAYS in the
    snapshot's future must actually be from the previous year.

    Falls back to the snapshot's own date if both are missing or malformed
    -- a best-effort report date is strictly better than dropping the
    record, and no worse than a NULL would have been.
    """
    candidate_text = None
    if description:
        prefix_match = re.match(r"^([A-Za-z]{3}\s+\d{1,2}):", description)
        if prefix_match:
            candidate_text = prefix_match.group(1)
    if candidate_text is None and isinstance(raw_date, str):
        candidate_text = raw_date

    match = _SHORT_DATE_RE.match(candidate_text) if candidate_text else None
    if not match:
        return snapshot_captured_at
    month = _MONTHS.get(match.group(1).title())
    if month is None:
        return snapshot_captured_at
    day = int(match.group(2))
    try:
        candidate = datetime(snapshot_captured_at.year, month, day, tzinfo=UTC)
    except ValueError:
        return snapshot_captured_at
    if (candidate - snapshot_captured_at).days > _YEAR_WRAP_THRESHOLD_DAYS:
        candidate = candidate.replace(year=candidate.year - 1)
    return candidate
