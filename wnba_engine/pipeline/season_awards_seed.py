"""One-off seed script: hand-researched WNBA season award winners (2022-2025)
-> season_awards table.

Why a plain seed script instead of a `backfill-*` CLI command (unlike
every other pipeline module in this directory): those all pull from a
live provider API and are re-run to pick up new data over time. Season
award winners are manually-researched historical fact fixed at the time
this was written -- see wnba_engine/pipeline/season_awards_data.py's
module docstring for the sources -- there is no API to poll and
re-running this against a future season would still only replay the same
constant list. Wiring it into wnba_engine/cli/main.py's `backfill-*`
family would misrepresent it as a live, growing pipeline. Run directly:

    uv run python -m wnba_engine.pipeline.season_awards_seed

Resolution: raw_name -> players.id via entity_repo.find_player_by_name
(read-only exact + diacritic-folding match, see that function's
docstring) for every award except Coach of the Year, which resolves
coach_team_name -> teams.id via entity_repo.find_team_by_name instead,
since a coach has no players.id row. Per this table's design (see
0017_season_awards.sql), an unresolved name is NOT an error and never
originates a new player/team row -- raw_name is always stored regardless,
player_id/team_id simply stay NULL, and the caller decides what to do
about the gap (see SeedResult.unresolved_names).

Idempotent: safe to re-run. Each row's dedup key is
(season, award, team_selection, raw_name) -- see season_awards_repo.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from wnba_engine.db.pool import Database
from wnba_engine.models.season_awards import AwardWinner
from wnba_engine.pipeline.season_awards_data import SEASON_AWARD_WINNERS
from wnba_engine.repositories import entity_repo, season_awards_repo


@dataclass(frozen=True, slots=True)
class SeedResult:
    records_seen: int = 0
    rows_inserted: int = 0
    rows_already_present: int = 0
    players_resolved: int = 0
    unresolved_names: tuple[str, ...] = ()
    coach_teams_resolved: int = 0
    unresolved_coach_teams: tuple[str, ...] = ()


def seed_season_awards(
    db: Database, records: tuple[AwardWinner, ...] = SEASON_AWARD_WINNERS
) -> SeedResult:
    result = SeedResult(records_seen=len(records))
    with db.connection() as conn:
        for record in records:
            player_id = None
            if record.coach_team_name is None:
                player_id = entity_repo.find_player_by_name(conn, record.raw_name)
                if player_id is not None:
                    result = replace(result, players_resolved=result.players_resolved + 1)
                else:
                    result = replace(
                        result, unresolved_names=result.unresolved_names + (record.raw_name,)
                    )

            team_id = None
            if record.coach_team_name is not None:
                team_id = entity_repo.find_team_by_name(conn, record.coach_team_name)
                if team_id is not None:
                    result = replace(result, coach_teams_resolved=result.coach_teams_resolved + 1)
                else:
                    result = replace(
                        result,
                        unresolved_coach_teams=result.unresolved_coach_teams
                        + (record.coach_team_name,),
                    )

            inserted = season_awards_repo.insert_award_winner(
                conn,
                season=record.season,
                award=record.award,
                team_selection=record.team_selection,
                player_id=player_id,
                raw_name=record.raw_name,
                team_id=team_id,
                source=record.source,
            )
            if inserted:
                result = replace(result, rows_inserted=result.rows_inserted + 1)
            else:
                result = replace(result, rows_already_present=result.rows_already_present + 1)
        conn.commit()
    return result


if __name__ == "__main__":
    import logging

    from wnba_engine.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = load_settings()
    database = Database(settings.database_url)
    try:
        outcome = seed_season_awards(database)
        print(outcome)
    finally:
        database.close()
