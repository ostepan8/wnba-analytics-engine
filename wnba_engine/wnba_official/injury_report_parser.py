"""Pure parser: official WNBA injury report text -> validated entries.

The league requires every team to file a participation status for each player
by 5pm local the day before a game (1pm for the second of a back-to-back), and
publishes the result as a PDF. That report is the ONLY source that carries the
real game-status designations:

    Probable   Questionable   Doubtful   Out

ESPN's feed -- the one this project used first -- publishes just `Out` and
`Day-To-Day` for the WNBA, on both its league-wide injuries endpoint and its
per-game summary. That is not merely coarser, it disagrees: on 2026-08-17 ESPN
had Jessica Shepard `Out` while the league's own 02:00 PM report had her
`Probable`. A probable starter shown as Out is a worse error than no label.

The PDF's text layer flattens to a single line per page, laid out as:

    Injury Report: 08/17/26 02:00 PM Page 1 of 1
    Game Date Game Time Matchup Team Player Name Current Status Reason
    08/17/2026 10:00 (ET) DAL@GSV Dallas Wings Fudd, Azzi Out Injury/Illness -
    Right Knee; right knee James, Aziaha Out Injury/Illness - Left Leg; ...
    Golden State Valkyries Salaun, Janelle Questionable Injury/Illness - ...

There are no delimiters: a player's reason runs until the next player, team, or
game begins. So the parse is anchor-based -- find every structural landmark in
document order, and treat whatever sits between two landmarks as the reason
belonging to the earlier one.

Team names are supplied by the caller rather than pattern-matched. A regex for
"a capitalised phrase that might be a team" cannot be distinguished from a
capitalised injury reason, and guessing wrong silently reassigns a player to the
opposing team. The caller knows the real names; this asks for them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.injuries import OfficialInjuryEntry

PROVIDER = "wnba_official"

# The four designations the league actually files. `Available` appears when a
# team clears a previously-listed player; it is kept because "was listed, now
# available" is information, and dropping it would leave the player showing
# yesterday's status.
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")

# A team that has not filed yet. Recorded as an absence rather than skipped
# silently, so a caller can tell "nobody is hurt" from "nobody has filed".
NOT_SUBMITTED = "NOT YET SUBMITTED"

_HEADER_RE = re.compile(
    r"Injury Report:\s*(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<time>\d{1,2}:\d{2})\s*(?P<meridiem>AM|PM)"
)

# "Shepard, Jessica Probable" -- surname, forename, then a designation.
#
# Both halves are deliberately tight. An earlier version allowed a name to span
# several capitalised words and produced "Janelle Golden State Valkyries Salaun"
# by swallowing the team header sitting in front of it. A surname is one token
# (hyphenated ones survive a space, because the PDF extractor splits
# "Parker-Tyus" as "Parker- Tyus"), and a forename is at most two.
_TOKEN = r"[A-Za-z'’.]+"
_SURNAME = rf"{_TOKEN}(?:\s*-\s*{_TOKEN})?"
_FORENAME = rf"{_TOKEN}(?:\s+{_TOKEN})?"
_PLAYER_RE = re.compile(
    rf"\b(?P<surname>{_SURNAME}),\s+(?P<forename>{_FORENAME}?)\s+"
    rf"(?P<status>{'|'.join(STATUSES)})\b"
)

_GAME_RE = re.compile(r"(?P<date>\d{2}/\d{2}/\d{4})")
_MATCHUP_RE = re.compile(r"\b(?P<away>[A-Z]{2,4})@(?P<home>[A-Z]{2,4})\b")
_COLUMN_HEADER = "Game Date Game Time Matchup Team Player Name Current Status Reason"


def flatten(text: str) -> str:
    """Collapse the PDF's per-token line breaks into one searchable string."""
    return re.sub(r"\s+", " ", text).strip()


def parse_report_timestamp(text: str) -> datetime:
    """The report's own filing time, from its header.

    This is the report's identity. Two filings on the same day differ only
    here, and stamping rows with the clock at fetch time would make an hourly
    re-fetch of an unchanged report look like new information.
    """
    match = _HEADER_RE.search(text)
    if match is None:
        raise ProviderValidationError(PROVIDER, "no 'Injury Report:' header found")
    hour = int(match["time"].split(":")[0]) % 12
    if match["meridiem"] == "PM":
        hour += 12
    month, day, year = (int(part) for part in match["date"].split("/"))
    return datetime(2000 + year, month, day, hour, int(match["time"].split(":")[1]), tzinfo=UTC)


def _landmarks(body: str, team_names: Sequence[str]) -> list[tuple[int, int, str, object]]:
    """Structural boundaries in document order: (start, end, kind, payload).

    Players are NOT included here. They are found in a second pass, scoped to
    the gaps between these landmarks, so a player name can never be built out
    of text that belongs to a team header or a game line.
    """
    found: list[tuple[int, int, str, object]] = []

    for name in team_names:
        for match in re.finditer(re.escape(name), body):
            found.append((match.start(), match.end(), "team", name))
    for match in _GAME_RE.finditer(body):
        found.append((match.start(), match.end(), "game", match["date"]))
    for match in _MATCHUP_RE.finditer(body):
        found.append((match.start(), match.end(), "matchup", match.group(0)))
    for match in re.finditer(re.escape(NOT_SUBMITTED), body):
        found.append((match.start(), match.end(), "unsubmitted", None))

    # Longest-first at a shared start, so "New York Liberty" wins over a team
    # whose name is a prefix of it.
    found.sort(key=lambda item: (item[0], -item[1]))

    kept: list[tuple[int, int, str, object]] = []
    for item in found:
        if kept and item[0] < kept[-1][1]:
            continue
        kept.append(item)
    return kept


def parse_injury_report(
    text: str,
    *,
    team_names: Sequence[str],
    captured_at: datetime | None = None,
) -> tuple[OfficialInjuryEntry, ...]:
    """Parse one report into flat per-player entries.

    `captured_at` defaults to the report's own filing time rather than now, so
    re-fetching an unchanged report is idempotent.
    """
    flat = flatten(text)
    reported_at = parse_report_timestamp(flat)
    captured_at = captured_at or reported_at

    body = flat.split(_COLUMN_HEADER, 1)[-1]
    marks = _landmarks(body, team_names)

    entries: list[OfficialInjuryEntry] = []
    team: str | None = None
    game_date: str | None = None
    matchup: str | None = None

    # Walk landmark-to-landmark. The span AFTER each landmark, up to the next
    # one, is the only place players are looked for.
    for index, (_, end, kind, payload) in enumerate(marks):
        if kind == "team":
            team = str(payload)
        elif kind == "game":
            game_date = str(payload)
        elif kind == "matchup":
            matchup = str(payload)
            # A new matchup ends the previous game's team context; without this
            # the first team of a game inherits the last team of the one before.
            team = None

        stop = marks[index + 1][0] if index + 1 < len(marks) else len(body)
        if team is None:
            # Text before any team header. Attributing a player here would mean
            # guessing her side, and a wrong team is worse than a missing row.
            continue
        entries.extend(
            _players_in(body[end:stop], team, game_date, matchup, reported_at, captured_at)
        )
    return tuple(entries)


def _players_in(
    span: str,
    team: str,
    game_date: str | None,
    matchup: str | None,
    reported_at: datetime,
    captured_at: datetime,
) -> list[OfficialInjuryEntry]:
    """Every player listed inside one team's span of the report."""
    matches = list(_PLAYER_RE.finditer(span))
    entries: list[OfficialInjuryEntry] = []
    for position, match in enumerate(matches):
        stop = matches[position + 1].start() if position + 1 < len(matches) else len(span)
        entries.append(
            OfficialInjuryEntry(
                player_name=_clean_name(f"{match['forename']} {match['surname']}"),
                team_name=team,
                status=match["status"],
                reason=_clean_reason(span[match.end() : stop]),
                game_date=game_date,
                matchup=matchup,
                reported_at=reported_at,
                captured_at=captured_at,
            )
        )
    return entries


def _clean_reason(raw: str) -> str | None:
    reason = raw.strip(" -;")
    return reason or None


def _clean_name(raw: str) -> str:
    """Repair the extractor's spacing before matching against real players.

    A hyphenated surname comes out of the PDF as "Parker- Tyus"; left alone it
    matches nobody, and an unmatched player is a player missing from the report.
    """
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", raw)).strip()


def teams_not_submitted(text: str, *, team_names: Sequence[str]) -> tuple[str, ...]:
    """Teams that appear on the report without having filed.

    Distinguishing "filed, nobody listed" from "has not filed" matters: the
    second is not evidence that a team is healthy.
    """
    flat = flatten(text)
    body = flat.split(_COLUMN_HEADER, 1)[-1]
    pending: list[str] = []
    team: str | None = None
    for _, _, kind, payload in _landmarks(body, team_names):
        if kind == "team":
            team = str(payload)
        elif kind == "unsubmitted" and team is not None:
            pending.append(team)
            team = None
    return tuple(pending)
