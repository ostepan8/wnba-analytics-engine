"""Named, pre-composed strategies -- the unit a caller swaps wholesale.

Factory functions rather than module constants, because every loader step
needs a FeatureRowSource and that source owns a live connection. A
module-level constant would either hold a connection for the process
lifetime or force a null-source placeholder that fails at run time.

Three of them, because two would not prove the point and one would not be
a strategy layer at all:

- `situational_baseline` -- home/road, rest, back-to-backs. The features
  ROADMAP.md Phase 1 names, and nothing else. Fast, no advanced-stats
  dependency, works for every season in the database.
- `team_form` -- baseline plus season-to-date record, rolling scoring and
  pace, standings-as-known, and encoding. What Phase 2's situational
  splits actually want.
- `player_form` -- player-game grain for prop work: rolling points /
  rebounds / assists / minutes, rest inherited from the team's schedule.

Swapping is the whole design:

    pipeline = strategies.build("team_form", source)
    lean = pipeline.without("rolling_form_5")
    with_standings = pipeline.with_steps(
        (loading.JoinStandingsSnapshotStep(source=source),)
    )

Order is not cosmetic. Filters that decide WHAT COUNTS AS A GAME run
before the windowed steps, or exhibitions against national teams end up
inside a "last 5 games" average; filters that decide what counts as a
usable ROW run after, because a garbage-time cameo is still a game the
team played. See `steps/filtering.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from wnba_engine.features.errors import FeatureError
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.source import FeatureRowSource
from wnba_engine.features.steps import cleaning, derivation, encoding, filtering, loading

StrategyFactory = Callable[[FeatureRowSource], Pipeline]

#: NUMERIC columns arrive from psycopg as decimal.Decimal, which raises
#: TypeError the moment it meets a float. Coerced once, up front, so no
#: downstream step has to know which columns came from a NUMERIC.
_TEAM_NUMERIC_COERCIONS = (
    ("pace", cleaning.TO_FLOAT),
    ("possessions", cleaning.TO_FLOAT),
    ("offensive_rating", cleaning.TO_FLOAT),
    ("defensive_rating", cleaning.TO_FLOAT),
)

_STANDINGS_COERCIONS = (
    ("standings_win_pct", cleaning.TO_FLOAT),
    ("standings_games_behind", cleaning.TO_FLOAT),
)

#: season_type is bounded by migration-era ESPN values and by
#: FeatureContext.season_types; listing them explicitly keeps the encoded
#: schema stable across boundaries (see steps/encoding.py on why there is
#: no fitted one-hot).
_SEASON_TYPE_CATEGORIES = ("regular-season", "post-season")
_HOME_AWAY_CATEGORIES = ("home", "away")


def situational_baseline(source: FeatureRowSource) -> Pipeline:
    """Minimal team-grain frame: home/road, rest days, back-to-backs."""
    return Pipeline(
        name="situational_baseline",
        steps=(
            loading.LoadTeamGamesStep(source=source),
            cleaning.CoerceTypesStep(
                coercions=_TEAM_NUMERIC_COERCIONS, step_name="coerce_team_numerics"
            ),
            filtering.FranchiseOnlyStep(),
            filtering.SeasonTypeStep(),
            filtering.SeasonsStep(),
            derivation.HomeAwayStep(),
            derivation.GameOutcomeStep(),
            derivation.RestDaysStep(),
        ),
    )


def team_form(source: FeatureRowSource) -> Pipeline:
    """Baseline plus rolling form, season-to-date record, opponent
    strength, and encoding.

    Standings are deliberately NOT here, even though
    `loading.JoinStandingsSnapshotStep` is correct and point-in-time safe.
    `team_standings_history` -- the only leak-free standings source, since
    `team_standings` is a current-state upsert -- begins at 2026-07-09.
    Every game before that has no snapshot to join, so the step
    contributes four all-null columns across 2022-2025. Columns null for
    ~97% of the frame are worse than absent: they invite imputation that
    invents a record no one observed, and they let a model's apparent
    reliance on "standings" really be a reliance on "is this a recent
    game". Add it back once that history accumulates:

        strategies.build("team_form", source).with_steps(
            (loading.JoinStandingsSnapshotStep(source=source),)
        )

    OPPONENT MIRRORS ARE PAIRED WITH THEIR SOURCE. Each
    `OpponentFormStep.mirroring(x)` reads the columns `x` produces, so
    removing or replacing `x` without doing the same to its mirror fails
    the frame contract. That is deliberate -- the alternative is a mirror
    that silently emits nulls and a model that quietly loses half the
    matchup -- but it means `.without("rolling_form_5")` must become
    `.without("rolling_form_5").without("opponent_rolling_form_5")`.
    """
    rolling_form = derivation.RollingMeanStep(
        value_columns=("points_scored", "points_allowed", "point_margin"),
        window=5,
        group_by=("team_id",),
        label="rolling_form_5",
    )
    rolling_pace = derivation.RollingMeanStep(
        value_columns=("pace",), window=5, group_by=("team_id",), label="rolling_pace_5"
    )
    season_to_date = derivation.SeasonToDateStep()
    return situational_baseline(source).renamed("team_form").with_steps(
        (
            season_to_date,
            rolling_form,
            rolling_pace,
            # The frame carried opponent_team_id and derived nothing from
            # it, so every model on it saw one half of each matchup.
            derivation.OpponentFormStep.mirroring(rolling_form),
            derivation.OpponentFormStep.mirroring(rolling_pace),
            # SeasonToDateStep publishes several columns without an
            # output_columns contract, so this one names what it mirrors.
            derivation.OpponentFormStep(
                value_columns=("season_win_pct_prior",),
                source_window_end_column="season_to_date__window_end",
                label="opponent_season_form",
            ),
            cleaning.FlagNullsStep(columns=("pace",)),
            encoding.OneHotStep(column="home_away", categories=_HOME_AWAY_CATEGORIES),
            encoding.OneHotStep(column="season_type", categories=_SEASON_TYPE_CATEGORIES),
            encoding.FitScaleStep(column="rest_days"),
        )
    )


def player_form(source: FeatureRowSource, *, minimum_minutes: int = 5) -> Pipeline:
    """Player-game grain for prop work.

    Rest is grouped by team_id, not player_id: rest is a property of the
    schedule the player's team played, and a player who missed a game did
    not thereby gain a day of rest.

    The minutes filter runs LAST, after the rolling windows, so a cameo
    still contributes to the player's own history even though the row
    itself is dropped -- removing it earlier would silently redefine
    "last 5 games" as "last 5 games with real minutes".
    """
    return Pipeline(
        name="player_form",
        steps=(
            loading.LoadPlayerGamesStep(source=source),
            filtering.SeasonTypeStep(),
            filtering.SeasonsStep(),
            derivation.HomeAwayStep(),
            derivation.RestDaysStep(group_by=("team_id",)),
            derivation.RollingMeanStep(
                value_columns=("points", "rebounds", "assists", "minutes"),
                window=5,
                group_by=("player_id",),
                label="rolling_player_5",
            ),
            loading.JoinPlayerBioStep(source=source),
            encoding.OneHotStep(column="home_away", categories=_HOME_AWAY_CATEGORIES),
            filtering.MinimumMinutesStep(minimum=minimum_minutes),
        ),
    )


#: The registry the CLI's --strategy flag resolves against. Adding a
#: strategy means adding a factory above and one line here; nothing else
#: in the codebase needs to know it exists.
STRATEGIES: Mapping[str, StrategyFactory] = {
    "situational_baseline": situational_baseline,
    "team_form": team_form,
    "player_form": player_form,
}


def build(name: str, source: FeatureRowSource) -> Pipeline:
    """Resolve a strategy by name, listing the alternatives on a miss."""
    factory = STRATEGIES.get(name)
    if factory is None:
        raise FeatureError(
            f"unknown feature strategy {name!r}; available: {sorted(STRATEGIES)}"
        )
    return factory(source)
