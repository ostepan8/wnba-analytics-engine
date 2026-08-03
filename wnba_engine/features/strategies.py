"""Named, pre-composed strategies -- the unit a caller swaps wholesale.

Factory functions rather than module constants, because every loader step
needs a FeatureRowSource and that source owns a live connection. A
module-level constant would either hold a connection for the process
lifetime or force a null-source placeholder that fails at run time.

Several of them, because one would not be a strategy layer at all:

- `situational_baseline` -- home/road, rest, back-to-backs. The features
  ROADMAP.md Phase 1 names, and nothing else. Fast, no advanced-stats
  dependency, works for every season in the database.
- `team_form` -- baseline plus season-to-date record, rolling scoring and
  pace, standings-as-known, and encoding. What Phase 2's situational
  splits actually want.
- `team_form_multi` -- team_form plus FEATURE_ROADMAP.md ss2: 10/20-game
  and season-to-date levels, exponential weighting, consistency, trend,
  home/road splits, streaks, and blowout rate.
- `team_matchup` -- team_form plus FEATURE_ROADMAP.md ss3: rest advantage,
  pace interaction, and head-to-head record at two horizons.
- `team_style` -- rolling style vectors and the matchup features they
  enable.
- `player_form` -- player-game grain for prop work: rolling points /
  rebounds / assists / minutes, rest inherited from the team's schedule.
- `player_rates` -- player_form plus FEATURE_ROADMAP.md ss5: per-36 rates,
  shot mix, minutes-weighted usage/TS/PIE, minutes share, starter rate.

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
from wnba_engine.features.step import PreprocessingStep
from wnba_engine.features.steps import (
    cleaning,
    derivation,
    encoding,
    filtering,
    form_steps,
    loading,
    market_steps,
    matchup_steps,
    player_steps,
    style_steps,
)

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
def team_style(source: FeatureRowSource) -> Pipeline:
    """Rolling STYLE vectors plus the matchup features they enable.

    Built on situational_baseline rather than team_form deliberately.
    team_form already rolls `pace` over a 5-game window, and
    RollingMeanStep names its output `{column}_mean_{window}` regardless
    of label -- so extending team_form would have two steps both claiming
    `pace_mean_5`. The frame guard catches that (it did), but the right
    fix is for style to be its own strategy rather than a bolt-on.

    The season-aggregate vectors in wnba_engine/analysis/style.py cannot
    be used as features -- a season aggregate contains the games it would
    predict. These rebuild the same dimensions from trailing windows, then
    derive what one team's vector cannot express:

    - `style_distance` and the per-dimension `*_gap` columns describe the
      MATCHUP. A stylistic mismatch is invisible in either team's own
      numbers, and the archetype work found matchup effects large enough
      to swamp home court -- perimeter teams beat grinders 74% at home.
    - `style_volatility` compares a 5-game window against a 15-game one,
      separating a settled identity from a team mid-reinvention. A single
      rolling average cannot tell those apart.

    Two windows over the same dimensions is the point, not duplication.
    """
    dims = style_steps.STYLE_DIMENSIONS
    short = derivation.RollingMeanStep(
        value_columns=dims, window=5, group_by=("team_id",), label="style_short"
    )
    long = derivation.RollingMeanStep(
        value_columns=dims, window=15, group_by=("team_id",), label="style_long"
    )
    mirror = derivation.OpponentFormStep.mirroring(short, label="opponent_style")
    return (
        situational_baseline(source)
        .renamed("team_style")
        .with_steps(
            (
                short,
                long,
                mirror,
                style_steps.StyleDistanceStep(
                    team_columns=short.output_columns,
                    opponent_columns=mirror.output_columns,
                    dimensions=dims,
                ),
                style_steps.StyleVolatilityStep(
                    short_columns=short.output_columns,
                    long_columns=long.output_columns,
                ),
            )
        )
    )


#: The value columns every ss2 multi-window step rolls. Scoring on both
#: sides plus the margin, because a team whose points_scored is drifting
#: up while its points_allowed drifts up faster is improving on offence
#: and getting worse overall, and only the margin says so.
_FORM_COLUMNS: tuple[str, ...] = ("points_scored", "points_allowed", "point_margin")

#: Longer windows for the shape statistics than for the level ones. A
#: standard deviation or a slope over 5 observations is mostly noise --
#: the sampling error on a 5-point sd is roughly a third of the sd -- so
#: they run at 10 while the means run at 5/10/20.
_SHAPE_WINDOW = 10

#: The home/road split window. FEATURE_ROADMAP.md flags thin samples here
#: and it is not a small effect: a team's tenth HOME game is around its
#: twentieth overall, so this window is only full late in a season.
#: `split_home__window_games` / `split_road__window_games` report the
#: real contribution per row, and a caller that wants to require a full
#: window should filter on those rather than trust the mean.
_SPLIT_WINDOW = 10


def team_form_multi(source: FeatureRowSource) -> Pipeline:
    """team_form plus FEATURE_ROADMAP.md ss2: many windows, and the shape
    of a team's form rather than only its level.

    A SEPARATE strategy rather than an extension of `team_form`, which is
    the decision most worth challenging here. Three reasons, in order of
    weight:

    1. `team_form` is the cheap, widely-used frame and this block roughly
       quadruples its windowed work (eleven passes over the frame instead
       of three). A caller wanting rest and a 5-game average should not
       pay for eleven.
    2. The two answer different questions. `team_form` describes a team's
       level; this describes the distribution its level was drawn from.
       Mixing them makes "which columns does my model actually use"
       harder to answer, not easier.
    3. Composability is the stated point of this package -- if extending
       a strategy is not the natural way to add features, the layering
       is decorative.

    The counter-argument is real and a reviewer should weigh it: two
    strategies whose first eighteen steps are identical will drift, and
    the roadmap describes ss2 as filling in `team_form` rather than as a
    new thing. If the multi-window block proves to be what everyone
    wants, collapsing this back into `team_form` is a one-line change and
    the right one.

    Steps are INSERTED after the last derivation step rather than
    appended, so the block sits with the other windowed work and ahead of
    the encoders. Position is currently immaterial -- `team_form` has no
    filter after its derivation block -- but `Pipeline.insert_after`
    exists so that adding a step is a choice of position rather than a
    default, and a future filter appended to `team_form` would otherwise
    silently start running before these windows instead of after.

    `MarginProfileStep` and the rolling mean over its flags are a PAIR.
    The flags describe the row's own game and are targets, exactly like
    `derivation.TARGET_COLUMNS`; the rolled `is_blowout_win_mean_10` is
    the feature. Dropping the rolling step and keeping the flags would
    hand a model the result.
    """
    block: tuple[PreprocessingStep, ...] = (
        # -- level, at three horizons plus season-to-date -------------
        derivation.RollingMeanStep(
            value_columns=_FORM_COLUMNS, window=10, group_by=("team_id",),
            label="rolling_form_10",
        ),
        derivation.RollingMeanStep(
            value_columns=_FORM_COLUMNS, window=20, group_by=("team_id",),
            label="rolling_form_20",
        ),
        form_steps.ExpandingMeanStep(value_columns=_FORM_COLUMNS, label="season_form"),
        form_steps.ExponentialMeanStep(
            value_columns=_FORM_COLUMNS, half_life_games=5.0, label="ewm_form_5"
        ),
        # -- shape: consistency, trend, splits ------------------------
        form_steps.RollingDispersionStep(
            value_columns=_FORM_COLUMNS, window=_SHAPE_WINDOW, label="dispersion_form_10"
        ),
        form_steps.RollingSlopeStep(
            value_columns=_FORM_COLUMNS, window=_SHAPE_WINDOW, label="slope_form_10"
        ),
        form_steps.SplitRollingMeanStep(
            value_columns=_FORM_COLUMNS, window=_SPLIT_WINDOW,
            split_column="is_home", split_value=True, suffix="home", label="split_home",
        ),
        form_steps.SplitRollingMeanStep(
            value_columns=_FORM_COLUMNS, window=_SPLIT_WINDOW,
            split_column="is_home", split_value=False, suffix="road", label="split_road",
        ),
        # -- streak and margin distribution ---------------------------
        form_steps.StreakStep(),
        form_steps.MarginProfileStep(),
        derivation.RollingMeanStep(
            value_columns=("is_blowout_win", "is_blowout_loss", "is_close_game"),
            window=_SHAPE_WINDOW,
            group_by=("team_id",),
            label="margin_profile_10",
        ),
    )
    pipeline = team_form(source).renamed("team_form_multi")
    anchor = "opponent_season_form"
    for step in block:
        pipeline = pipeline.insert_after(anchor, step)
        anchor = step.name
    return pipeline


def team_matchup(source: FeatureRowSource) -> Pipeline:
    """team_form plus FEATURE_ROADMAP.md ss3: what the two teams are
    RELATIVE to each other.

    Built on `team_form` rather than on `team_form_multi`, which is the
    decision most worth challenging here. The three ss3 features need
    exactly two things from upstream -- `rest_days` and `pace_mean_5`,
    both of which `team_form` already produces -- so the multi-window
    block would be eleven steps of cost for nothing this strategy reads.
    Anyone wanting both can compose them, and the composition is the
    reason `PaceInteractionStep` takes its column names as config rather
    than hard-coding `pace_mean_5`:

        strategies.build("team_form_multi", source).with_steps(
            matchup_block()
        )

    The counter-argument: three strategies now share the same eighteen-step
    prefix and can drift apart. That is the same tension `team_form_multi`
    records, and the same answer applies -- collapsing them is cheap and
    splitting them back apart is not.

    A REST MIRROR IS ADDED HERE, not in team_form. `team_form` mirrors
    rolling form, rolling pace and season record but not rest, so
    `opponent_rest_days` does not exist until this strategy creates it.
    That mirror and `RestAdvantageStep` are a pair in exactly the sense
    `OpponentFormStep.mirroring` describes: dropping `rest_days` breaks
    both, loudly.
    """
    return team_form(source).renamed("team_matchup").with_steps(matchup_block())


def matchup_block() -> tuple[PreprocessingStep, ...]:
    """The ss3 steps, in dependency order.

    A function rather than a module constant because the steps are values
    and sharing one tuple between strategies would be fine -- but the
    mirror below is derived from column names `team_form` chose, and
    keeping the derivation next to the strategy that relies on it is the
    thing that makes a rename fail visibly.
    """
    return (
        # RestDaysStep publishes no `output_columns` contract (it adds two
        # unrelated columns rather than one per input), so the mirror
        # names what it copies instead of using `.mirroring()`.
        derivation.OpponentFormStep(
            value_columns=("rest_days", "is_back_to_back"),
            source_window_end_column=f"rest_days{derivation.WINDOW_END_SUFFIX}",
            label="opponent_rest",
        ),
        matchup_steps.RestAdvantageStep(),
        matchup_steps.PaceInteractionStep(),
        # Two head-to-head horizons, both unbounded within their key.
        # Season: typically 0-3 prior meetings, very noisy, and the only
        # one describing the current rosters. All-time: up to ~20
        # meetings across five seasons of turnover. FEATURE_ROADMAP.md
        # asks for both and neither dominates.
        matchup_steps.HeadToHeadStep(prefix="h2h_season", season_column="season"),
        matchup_steps.HeadToHeadStep(prefix="h2h_all", season_column=None),
    )


#: The counting stats a per-36 rate is taken over. These are exactly
#: analysis/style.py's PLAYER_DIMENSIONS minus the shares and the
#: provider-computed rates, so a trailing vector built here is comparable
#: to the season vector built there.
_PER36_NUMERATORS: tuple[str, ...] = (
    "points",
    "rebounds",
    "assists",
    "three_pointers_made",
    "steals",
    "blocks",
    "turnovers",
)

#: Rates balldontlie computed from inputs this database does not store,
#: so they cannot be re-derived as a ratio of sums and are instead
#: minutes-weighted. See RollingWeightedMeanStep.
_ADVANCED_RATES: tuple[str, ...] = (
    "usage_pct",
    "true_shooting_pct",
    "assist_pct",
    "rebound_pct",
    "pie",
)

#: NUMERIC again -- psycopg hands these back as decimal.Decimal, and a
#: Decimal meeting a float raises TypeError inside the first window.
_PLAYER_NUMERIC_COERCIONS = tuple((column, cleaning.TO_FLOAT) for column in _ADVANCED_RATES)

#: The rolling window for every player rate. 10 rather than the team
#: side's 5, because a player-grain window is thinner than it looks: a
#: DNP contributes NULL minutes (db/migrations/0002_box_scores.sql) and
#: drops out of the ratio entirely, so a 5-game window on a
#: load-managed player can describe two games. Every rate step publishes
#: `<label>__window_games` so the real depth stays visible.
_PLAYER_WINDOW = 10


def player_rates(source: FeatureRowSource, *, minimum_minutes: int = 5) -> Pipeline:
    """player_form plus FEATURE_ROADMAP.md ss5: rates, role, and the
    trailing player style vector.

    Everything here is a RATIO, and MODELING_FINDINGS.md records what the
    wrong kind of ratio costs -- an 8.0045 MAE against a 3.05 baseline,
    from averaging `stat/minutes` per game instead of taking a ratio of
    sums. `player_steps` is built around the correct form; this strategy
    just chooses the columns.

    Four ss5 rows, three shapes:

    - PER-36 RATES and SHOT-MIX SHARES are the same step at different
      scales. `points_per36_10` divides summed points by summed minutes
      and multiplies by 36; `three_pointers_attempted_share_of_fga_10`
      divides summed threes by summed attempts at scale 1.
    - USAGE / TS / PIE arrive already divided, so they are
      minutes-weighted rather than summed.
    - MINUTES SHARE needs a denominator on other rows, so it is its own
      step. Note what is NOT here: this game's minutes share. It would
      require tonight's rotation, the guard would reject it, and the
      guard would be right -- see RollingShareStep.

    STARTER RATE gets no new class. A rolling mean over a boolean IS a
    rate, and `starter` is NOT NULL in player_game_stats, so
    `starter_mean_10` is a genuine 0-1 fraction rather than a fraction of
    the games we happen to know about.

    THE MINUTES FILTER MUST STAY LAST, and every step here is INSERTED
    before it rather than appended. `player_form` ends with
    `minimum_minutes`, so `.with_steps(...)` would put these windows
    AFTER it -- and that is not a stylistic point:

    - Every rate would be computed over "games with at least 5 minutes",
      silently redefining a 10-game window as 10 qualifying games. That
      HIDES the low-minute bias a ratio of sums exists to handle rather
      than fixing it, and it hides it in the direction that looks fine.
    - `RollingShareStep` would be worse than biased. Its denominator is
      the TEAM's minutes summed across the rotation, and a filtered frame
      has no rows for the players who played four minutes -- so every
      team total would be short and every share inflated, with no null or
      error to show for it.

    This was not a hypothetical: the first version of this factory
    appended, and `test_player_rates_keeps_the_minutes_filter_last`
    caught it.
    """
    rate_block: tuple[PreprocessingStep, ...] = (
        player_steps.RollingRateStep(
            value_columns=_PER36_NUMERATORS,
            denominator_column="minutes",
            window=_PLAYER_WINDOW,
            scale=player_steps.PER_36,
            suffix="per36",
            label="per36_10",
        ),
        # Shot mix. Scale 1, so these read as fractions.
        player_steps.RollingRateStep(
            value_columns=("three_pointers_attempted", "free_throws_attempted"),
            denominator_column="field_goals_attempted",
            window=_PLAYER_WINDOW,
            scale=1.0,
            suffix="share_of_fga",
            label="shot_mix_10",
        ),
        player_steps.RollingRateStep(
            value_columns=("offensive_rebounds",),
            denominator_column="rebounds",
            window=_PLAYER_WINDOW,
            scale=1.0,
            suffix="share_of_reb",
            label="reb_mix_10",
        ),
        player_steps.RollingWeightedMeanStep(
            value_columns=_ADVANCED_RATES,
            weight_column="minutes",
            window=_PLAYER_WINDOW,
            label="advanced_10",
        ),
        player_steps.RollingShareStep(
            value_column="minutes", window=_PLAYER_WINDOW, label="minutes_share_10"
        ),
        derivation.RollingMeanStep(
            value_columns=("starter",),
            window=_PLAYER_WINDOW,
            group_by=("player_id",),
            label="starter_rate_10",
        ),
        # The advanced join is ~7.5% null against ESPN box scores (28,989
        # of 31,340 matched, verified 2026-08-02), so the flag keeps "no
        # advanced row" distinguishable from "a usage rate of zero" the
        # way FlagNullsStep does for pace.
        cleaning.FlagNullsStep(columns=("usage_pct",), step_name="flag_advanced_nulls"),
    )
    pipeline = (
        player_form(source, minimum_minutes=minimum_minutes)
        .renamed("player_rates")
        # Coercion must precede every window: the advanced columns are
        # NUMERIC, and a Decimal meeting a float raises TypeError.
        .insert_after(
            "load_player_games",
            cleaning.CoerceTypesStep(
                coercions=_PLAYER_NUMERIC_COERCIONS, step_name="coerce_player_rates"
            ),
        )
    )
    anchor = "rolling_player_5"
    for step in rate_block:
        pipeline = pipeline.insert_after(anchor, step)
        anchor = step.name
    return pipeline


def team_market(source: FeatureRowSource) -> Pipeline:
    """team_form plus FEATURE_ROADMAP.md ss8: what the MARKET thought.

    A SEPARATE strategy, and this one is not a cost argument like
    `team_form_multi`'s -- it is a containment argument, and the roadmap
    states it directly: "Keep market features in a separate strategy so
    they can never silently enter a 'pure basketball' model."

    The line is the best single forecast of a game that exists. A frame
    holding it will beat every basketball feature in this package on any
    metric, and will have taught nothing, because it is a copy of someone
    else's model rather than a description of the teams. Anyone comparing
    strategies needs to be unable to include these by accident.

    What it IS good for: measuring whether anything else here adds
    information the market has not already priced. MODELING_FINDINGS.md
    records that nothing has yet -- residual correlation of -0.031/-0.041
    against the closing line -- and this strategy is how that gets
    re-tested as features are added.

    Both joins are per ROW. The two venues need opposite handling and both
    are documented in market_steps: books are de-vigged per book before
    aggregating, Polymarket needs no de-vig at all.
    """
    return (
        team_form(source)
        .renamed("team_market")
        .with_steps(
            (
                market_steps.JoinMarketOddsStep(source=source),
                market_steps.JoinPredictionMarketStep(source=source),
                market_steps.MarketDivergenceStep(),
            )
        )
    )


def player_market(source: FeatureRowSource, *, minimum_minutes: int = 5) -> Pipeline:
    """player_form plus the player-grain half of FEATURE_ROADMAP.md ss8.

    Separate from `team_market` because the grain differs, and separate
    from `player_form` for the same containment reason `team_market` is
    separate from `team_form`: the prop line is a forecast someone else
    made, and a frame holding it will outperform every basketball feature
    here while explaining nothing.

    Adds its OWN rolling mean for three-pointers. `player_form` rolls
    points, rebounds, assists and minutes but not threes, so
    `three_pointers_made_mean_5` does not otherwise exist -- and
    `PropLineEdgeStep` names the columns it reads explicitly rather than
    guessing them, so a missing one fails the frame contract loudly
    instead of emitting silent nulls (which is exactly how
    `StyleDistanceStep` shipped broken once).
    """
    pipeline = (
        player_form(source, minimum_minutes=minimum_minutes)
        .renamed("player_market")
        .insert_after(
            "rolling_player_5",
            derivation.RollingMeanStep(
                value_columns=("three_pointers_made",),
                window=5,
                group_by=("player_id",),
                label="rolling_player_threes_5",
            ),
        )
    )
    return pipeline.with_steps(
        (
            market_steps.JoinPlayerPropLineStep(source=source),
            market_steps.PropLineEdgeStep(),
        )
    )


STRATEGIES: Mapping[str, StrategyFactory] = {
    "situational_baseline": situational_baseline,
    "team_form": team_form,
    "team_form_multi": team_form_multi,
    "team_market": team_market,
    "team_matchup": team_matchup,
    "team_style": team_style,
    "player_form": player_form,
    "player_market": player_market,
    "player_rates": player_rates,
}


def build(name: str, source: FeatureRowSource) -> Pipeline:
    """Resolve a strategy by name, listing the alternatives on a miss."""
    factory = STRATEGIES.get(name)
    if factory is None:
        raise FeatureError(
            f"unknown feature strategy {name!r}; available: {sorted(STRATEGIES)}"
        )
    return factory(source)
