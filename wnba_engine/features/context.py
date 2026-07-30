"""The point-in-time boundary every step is evaluated against.

`as_of` is the single most important value in this subsystem: it is the
instant beyond which NO observation may reach a feature. Everything else
here (seasons, season_types) is ordinary scope narrowing.

Why the context is passed to every step rather than baked into the
Pipeline: the same Pipeline object is meant to be re-run at many
boundaries (a walk-forward backtest is exactly "one Pipeline, N contexts").
Binding as_of to the Pipeline would force rebuilding the whole strategy
per fold, and the natural way to avoid that rebuild is to mutate the
boundary in place -- which is how backtests leak.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

# Preseason has non-franchise opponents (national teams, club sides) and
# All-Star games ('other') have roster constructs like "TEAM CLARK" -- see
# DATA_INVENTORY.md's coverage-boundaries section. Neither is priced by
# sportsbooks, and both distort any rest/form feature that treats them as
# real games, so the default scope excludes them. Override deliberately.
from wnba_engine.repositories.feature_repo import DEFAULT_COMPLETION_MARGIN

DEFAULT_SEASON_TYPES: tuple[str, ...] = ("regular-season", "post-season")


@dataclass(frozen=True, slots=True)
class FeatureContext:
    """Scope + boundary for one feature build.

    `seasons` empty means "every season" -- an explicit empty tuple rather
    than None so the field is always a tuple and callers never branch on
    two different "unset" shapes.
    """

    as_of: datetime
    seasons: tuple[int, ...] = ()
    season_types: tuple[str, ...] = DEFAULT_SEASON_TYPES
    #: Fallback for how long after tip-off a result is assumed knowable,
    #: used ONLY where `games.final_observed_at` is NULL -- i.e. games that
    #: were already final when first ingested, so nothing witnessed the
    #: transition (see db/migrations/0024_game_final_observed_at.sql).
    #: Lives on the context rather than on each loader because it is part
    #: of what `as_of` MEANS for this build; two loaders disagreeing about
    #: it would make one frame's boundary depend on which step produced a
    #: row.
    completion_margin: timedelta = DEFAULT_COMPLETION_MARGIN

    def __post_init__(self) -> None:
        # A naive as_of is the most dangerous possible input here: every
        # timestamp column in this database is TIMESTAMPTZ, so psycopg
        # returns tz-aware datetimes, and comparing those to a naive
        # boundary raises TypeError deep inside the guard -- or, worse, a
        # caller "fixes" it by stripping tzinfo from the DATA and silently
        # shifts the boundary by hours. Reject it at the door instead.
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError(
                "FeatureContext.as_of must be timezone-aware "
                "(every timestamp in this database is TIMESTAMPTZ); "
                f"got {self.as_of!r}"
            )
        if not self.season_types:
            raise ValueError("FeatureContext.season_types must not be empty")

    def with_as_of(self, as_of: datetime) -> FeatureContext:
        """A copy at a new boundary -- the walk-forward backtest primitive."""
        return replace(self, as_of=as_of)

    def with_seasons(self, seasons: tuple[int, ...]) -> FeatureContext:
        return replace(self, seasons=seasons)

    def with_season_types(self, season_types: tuple[str, ...]) -> FeatureContext:
        return replace(self, season_types=season_types)

    def describe(self) -> str:
        seasons = ",".join(str(s) for s in self.seasons) if self.seasons else "all"
        return (
            f"as_of={self.as_of.isoformat()} seasons={seasons} "
            f"season_types={'/'.join(self.season_types)}"
        )
