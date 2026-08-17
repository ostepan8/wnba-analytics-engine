"""Official WNBA injury report -> injury_reports rows, source 'wnba_official'.

Why a second injury source at all: ESPN's feed, which this project used first,
publishes only `Out` and `Day-To-Day` for the WNBA. The league's own report
carries the designations teams actually file -- Probable, Questionable,
Doubtful, Out -- and the two disagree. On 2026-08-17 ESPN had Jessica Shepard
`Out` while the league's 02:00 PM report had her `Probable`.

No migration: injury_reports already carries a `source` column and is keyed on
(source, player_id, captured_at), so official rows sit alongside ESPN's and
readers choose. form_repo prefers this source and falls back to ESPN for
players the report does not mention.

Resolution is by NAME, because the report carries no ids. That is the same
shape of problem that once put the wrong player on 43% of prop rows, so the
rule from that repair holds here: a name that does not resolve to exactly one
known player is dropped and counted, never guessed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from wnba_engine.db.pool import Database
from wnba_engine.models.injuries import OfficialInjuryEntry
from wnba_engine.repositories import entity_repo, injury_repo
from wnba_engine.wnba_official.client import WnbaOfficialClient, extract_text
from wnba_engine.wnba_official.injury_report_parser import (
    parse_injury_report,
    teams_not_submitted,
)

logger = logging.getLogger(__name__)

SOURCE = "wnba_official"


@dataclass(frozen=True, slots=True)
class OfficialInjuryIngestResult:
    report_url: str | None = None
    entries_seen: int = 0
    entries_inserted: int = 0
    unresolved_players: int = 0
    teams_not_submitted: int = 0

    def __str__(self) -> str:
        if self.report_url is None:
            return "no official injury report published"
        return (
            f"{self.entries_inserted} inserted of {self.entries_seen} listed "
            f"({self.unresolved_players} unresolved, "
            f"{self.teams_not_submitted} teams not yet filed) from {self.report_url}"
        )


def ingest_official_injury_report(
    db: Database,
    client: WnbaOfficialClient,
    *,
    captured_at: datetime | None = None,
) -> OfficialInjuryIngestResult:
    """Fetch, parse and store the league's current injury report."""
    document = client.fetch_latest()
    if document is None:
        return OfficialInjuryIngestResult()

    text = extract_text(document.content)

    with db.connection() as conn:
        teams = entity_repo.list_team_names(conn)
        team_id_by_name = {name: team_id for team_id, name in teams}
        entries = parse_injury_report(
            text, team_names=list(team_id_by_name), captured_at=captured_at
        )
        pending = teams_not_submitted(text, team_names=list(team_id_by_name))

        resolved: list[tuple[int, int, OfficialInjuryEntry]] = []
        unresolved = 0
        for entry in entries:
            team_id = team_id_by_name.get(entry.team_name)
            player_id = entity_repo.find_player_by_name(conn, entry.player_name)
            if team_id is None or player_id is None:
                # NULL beats wrong: an unmatched name is reported, not attached
                # to the nearest-looking player.
                logger.warning(
                    "unresolved official injury entry player=%r team=%r -- skipping",
                    entry.player_name,
                    entry.team_name,
                )
                unresolved += 1
                continue
            resolved.append((player_id, team_id, entry))

        inserted = injury_repo.insert_official_snapshots(conn, resolved, source=SOURCE)

    return OfficialInjuryIngestResult(
        report_url=document.url,
        entries_seen=len(entries),
        entries_inserted=inserted,
        unresolved_players=unresolved,
        teams_not_submitted=len(pending),
    )
