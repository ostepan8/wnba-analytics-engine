"""Pure parser: raw ESPN injuries JSON -> validated domain models.

Payload shape (site.api.espn.com/.../injuries), current-state only (see
0005_injury_reports.sql migration comment -- this is NOT a historical feed):
  injuries[] -> id, displayName (team, no abbreviation on this endpoint),
                injuries[] -> id, status, date, type{name}, details{...},
                              shortComment, longComment,
                              athlete{displayName, position, links[]}

The athlete's ESPN id isn't a direct field here (unlike the box score
payload) -- it's extracted from the "playercard" link URL
(.../player/_/id/<id>/<slug>).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.box_scores import PlayerRef
from wnba_engine.models.injuries import InjuryReportEntry, InjuryTeamRef
from wnba_engine.parsing import (
    parse_datetime_utc,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "espn"

_PLAYERCARD_ID_RE = re.compile(r"/player/_/id/(\d+)/")


def parse_injuries(payload: object, *, captured_at: datetime) -> tuple[InjuryReportEntry, ...]:
    """Parse a full /injuries response into flat per-player entries."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"injuries payload must be an object, got {type(payload).__name__}"
        )
    team_blocks = require_sequence(payload, "injuries", PROVIDER, "injuries")
    entries: list[InjuryReportEntry] = []
    for i, block in enumerate(team_blocks):
        entries.extend(_parse_team_block(block, f"injuries[{i}]", captured_at))
    return tuple(entries)


def _parse_team_block(
    block: object, context: str, captured_at: datetime
) -> tuple[InjuryReportEntry, ...]:
    if not isinstance(block, Mapping):
        raise ProviderValidationError(PROVIDER, "team block must be an object", context=context)
    team = InjuryTeamRef(
        external_id=require_str(block, "id", PROVIDER, context),
        name=require_str(block, "displayName", PROVIDER, context),
    )
    raw_injuries = require_sequence(block, "injuries", PROVIDER, context)
    return tuple(
        _parse_injury(entry, team, f"{context}.injuries[{j}]", captured_at)
        for j, entry in enumerate(raw_injuries)
    )


def _parse_injury(
    entry: object, team: InjuryTeamRef, context: str, captured_at: datetime
) -> InjuryReportEntry:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "injury entry must be an object", context=context)
    player = _parse_athlete(
        require_mapping(entry, "athlete", PROVIDER, context), f"{context}.athlete"
    )
    status_type = require_mapping(entry, "type", PROVIDER, context)
    details = entry.get("details")
    details = details if isinstance(details, Mapping) else {}
    return InjuryReportEntry(
        espn_injury_id=require_str(entry, "id", PROVIDER, context),
        player=player,
        team=team,
        status=require_str(entry, "status", PROVIDER, context),
        status_type=require_str(status_type, "name", PROVIDER, f"{context}.type"),
        injury_type=_optional_str(details.get("type")),
        side=_optional_str(details.get("side")),
        return_date=_optional_date(details.get("returnDate"), f"{context}.details.returnDate"),
        short_comment=_optional_str(entry.get("shortComment")),
        long_comment=_optional_str(entry.get("longComment")),
        reported_at=parse_datetime_utc(
            require(entry, "date", PROVIDER, context), PROVIDER, f"{context}.date"
        ),
        captured_at=captured_at,
    )


def _parse_athlete(athlete: Mapping[str, object], context: str) -> PlayerRef:
    full_name = require_str(athlete, "displayName", PROVIDER, context)
    links = athlete.get("links")
    links = links if isinstance(links, Sequence) and not isinstance(links, (str, bytes)) else []
    playercard_href = next(
        (
            link.get("href")
            for link in links
            if isinstance(link, Mapping) and "playercard" in (link.get("rel") or [])
        ),
        None,
    )
    match = _PLAYERCARD_ID_RE.search(playercard_href) if isinstance(playercard_href, str) else None
    if not match:
        raise ProviderValidationError(
            PROVIDER, "could not extract athlete id from playercard link", context=context
        )
    position = athlete.get("position")
    position_abbr = position.get("abbreviation") if isinstance(position, Mapping) else None
    return PlayerRef(
        external_id=match.group(1),
        full_name=full_name,
        position=position_abbr if isinstance(position_abbr, str) else None,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _optional_date(value: object, context: str) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProviderValidationError(
            PROVIDER, f"invalid ISO date {value!r}", context=context
        ) from exc
