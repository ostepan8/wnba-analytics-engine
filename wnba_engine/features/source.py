"""Where loader steps get their rows.

A narrow Protocol between the steps and Postgres, for two reasons that
both matter more than the usual "testability" argument:

- Unit tests can drive the ENTIRE step/guard/pipeline stack on
  hand-written rows, including the adversarial ones. The most valuable
  leakage tests are the ones that construct a deliberately-poisoned row
  (a standings snapshot captured tomorrow, a rolling window ending after
  tip-off) and assert the guard rejects it -- and those rows cannot be
  produced by a correct database.
- Loader steps stay declarative. A step's job is to declare provenance
  and hand back rows; connection lifecycle is the caller's.

`PostgresRowSource` holds an open connection rather than a Database pool:
one feature build should read every table at one consistent point in the
transaction, not open a fresh connection per loader and pick up whatever
the 2-hourly ingestion jobs wrote in between.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from psycopg import Connection

from wnba_engine.features.context import FeatureContext
from wnba_engine.repositories import feature_repo

Row = Mapping[str, object]

#: Which of the two independent box-score sources a player-grain feature
#: build reads. ESPN is the default because it is the sole source of
#: games.home_score/away_score, so player rows and game outcomes come from
#: one provider rather than two that disagree by 1-2 points on ~0.5% of
#: games (see DATA_INVENTORY.md's plays_final_score check).
DEFAULT_BOX_SCORE_SOURCE = "espn"


class FeatureRowSource(Protocol):
    """Raw rows for the loader steps, already bounded by `context.as_of`."""

    def team_games(self, context: FeatureContext) -> tuple[Row, ...]: ...

    def player_games(self, context: FeatureContext) -> tuple[Row, ...]: ...

    def standings_snapshots(self, context: FeatureContext) -> tuple[Row, ...]: ...

    def player_bios(self) -> tuple[Row, ...]: ...


@dataclass(frozen=True, slots=True)
class PostgresRowSource:
    """The real source: `wnba_engine/repositories/feature_repo.py`."""

    conn: Connection
    box_score_source: str = DEFAULT_BOX_SCORE_SOURCE

    def team_games(self, context: FeatureContext) -> tuple[Row, ...]:
        return feature_repo.load_team_games(
            self.conn,
            as_of=context.as_of,
            season_types=context.season_types,
            seasons=context.seasons or None,
        )

    def player_games(self, context: FeatureContext) -> tuple[Row, ...]:
        return feature_repo.load_player_games(
            self.conn,
            as_of=context.as_of,
            season_types=context.season_types,
            seasons=context.seasons or None,
            box_score_source=self.box_score_source,
        )

    def standings_snapshots(self, context: FeatureContext) -> tuple[Row, ...]:
        return feature_repo.load_standings_snapshots(
            self.conn, as_of=context.as_of, seasons=context.seasons or None
        )

    def player_bios(self) -> tuple[Row, ...]:
        return feature_repo.load_player_bios(self.conn)


@dataclass(frozen=True, slots=True)
class StaticRowSource:
    """An in-memory source for tests and for replaying a captured frame.

    Deliberately does NOT filter by as_of: it exists so a test can feed
    rows the database could never produce -- including rows that violate
    the boundary -- and assert the guard catches them. A source that
    quietly sanitised its input would make those tests pass for the wrong
    reason.
    """

    team_game_rows: Sequence[Row] = ()
    player_game_rows: Sequence[Row] = ()
    standings_rows: Sequence[Row] = ()
    bio_rows: Sequence[Row] = ()

    def team_games(self, context: FeatureContext) -> tuple[Row, ...]:
        return tuple(self.team_game_rows)

    def player_games(self, context: FeatureContext) -> tuple[Row, ...]:
        return tuple(self.player_game_rows)

    def standings_snapshots(self, context: FeatureContext) -> tuple[Row, ...]:
        return tuple(self.standings_rows)

    def player_bios(self) -> tuple[Row, ...]:
        return tuple(self.bio_rows)
