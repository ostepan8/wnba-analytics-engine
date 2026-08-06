"""Deliberately minimal CLI: migrate + one ingest command per provider.

Just enough to smoke-test the pipeline by hand; real CLI polish is a
separate, later task.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, date, timedelta
from pathlib import Path

import click

from wnba_engine.analysis import style as style_space
from wnba_engine.analysis.divergence import DEFAULT_MIN_VOLUME
from wnba_engine.analysis.lead_lag import t_statistic as lead_lag_t
from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.config import load_settings
from wnba_engine.db.migrate import run_migrations
from wnba_engine.db.pool import Database
from wnba_engine.espn.client import EspnClient
from wnba_engine.espn.wayback_client import WaybackClient
from wnba_engine.features.context import FeatureContext
from wnba_engine.features.strategies import STRATEGIES as FEATURE_STRATEGIES
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.odds_api.client import OddsApiClient
from wnba_engine.pipeline.balldontlie_advanced_stats_ingest import backfill_season
from wnba_engine.pipeline.balldontlie_injury_ingest import snapshot_current_injuries
from wnba_engine.pipeline.balldontlie_odds_ingest import (
    backfill_date_range as backfill_odds_date_range,
)
from wnba_engine.pipeline.balldontlie_player_prop_odds_ingest import (
    backfill_season as backfill_player_prop_odds_season,
)
from wnba_engine.pipeline.balldontlie_players_ingest import backfill_players
from wnba_engine.pipeline.balldontlie_plays_ingest import backfill_season_plays
from wnba_engine.pipeline.balldontlie_shot_zone_ingest import backfill_season_shot_zones
from wnba_engine.pipeline.balldontlie_standings_ingest import (
    backfill_season as backfill_standings_season,
)
from wnba_engine.pipeline.balldontlie_stats_ingest import (
    backfill_season as backfill_balldontlie_stats_season,
)
from wnba_engine.pipeline.balldontlie_team_advanced_stats_ingest import (
    backfill_season as backfill_team_advanced_stats_season,
)
from wnba_engine.pipeline.clv_report import build_clv_report
from wnba_engine.pipeline.divergence_log import (
    grade_closings,
    log_divergences,
    recheck_prices,
)
from wnba_engine.pipeline.divergence_report import build_divergence_report
from wnba_engine.pipeline.espn_ingest import backfill, sync_date
from wnba_engine.pipeline.espn_transactions_ingest import (
    backfill_season as backfill_transactions_season,
)
from wnba_engine.pipeline.feature_build import build_features
from wnba_engine.pipeline.focused_odds_capture import (
    DEFAULT_MIN_FILLS,
    capture_focused_odds,
)
from wnba_engine.pipeline.injury_ingest import ingest_current_injury_report
from wnba_engine.pipeline.kalshi_candle_backfill import (
    DERIVATIVE_SERIES,
    GAME_SERIES,
    backfill_kalshi_candles,
)
from wnba_engine.pipeline.kalshi_ingest import ingest_kalshi_wnba_markets
from wnba_engine.pipeline.kalshi_trade_backfill import backfill_kalshi_trades
from wnba_engine.pipeline.lead_lag_report import build_lead_lag_report
from wnba_engine.pipeline.market_capture_ingest import ingest_captures
from wnba_engine.pipeline.market_game_relink import relink_market_snapshots
from wnba_engine.pipeline.odds_api_ingest import backfill_history as backfill_odds_api_history
from wnba_engine.pipeline.odds_api_ingest import snapshot_current_odds as snapshot_odds_api_odds
from wnba_engine.pipeline.odds_api_player_props_ingest import (
    backfill_props_history as backfill_odds_api_props_history,
)
from wnba_engine.pipeline.odds_api_player_props_ingest import (
    snapshot_current_props as snapshot_odds_api_props,
)
from wnba_engine.pipeline.odds_api_scores_ingest import (
    snapshot_current_scores as snapshot_odds_api_scores,
)
from wnba_engine.pipeline.polymarket_ingest import ingest_polymarket_wnba_markets
from wnba_engine.pipeline.polymarket_trade_backfill import backfill_polymarket_trades
from wnba_engine.pipeline.wayback_injury_backfill import backfill_injury_history
from wnba_engine.pipeline.wnba_stats_ingest import ingest_season as ingest_wnba_stats_season
from wnba_engine.polymarket.client import PolymarketClient
from wnba_engine.polymarket.data_client import PolymarketDataClient
from wnba_engine.repositories import style_repo
from wnba_engine.validation.runner import run_all_checks
from wnba_engine.wnba_stats.client import WnbaStatsClient


@click.group()
def cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # httpx logs "HTTP Request: GET <full url incl. query string>" at INFO
    # for every request. For header-auth providers that's harmless, but
    # for a query-param-auth provider (the-odds-api's apiKey=...) it would
    # print the raw API key in cleartext to stdout/logs -- our own
    # JsonHttpClient redacts it (see redact_query_param_keys), but httpx's
    # own internal logger is a separate code path that bypasses that
    # entirely. Silencing it here is a global, defense-in-depth fix, not
    # specific to the-odds-api -- any future query-param-auth provider
    # would have the same problem otherwise.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@cli.command()
def migrate() -> None:
    """Apply pending SQL migrations."""
    db = Database(load_settings().database_url)
    try:
        applied = run_migrations(db)
        click.echo(f"applied: {applied or 'nothing (up to date)'}")
    finally:
        db.close()


@cli.command("sync-espn")
@click.option("--date", "day", type=click.DateTime(["%Y-%m-%d"]), required=True)
def sync_espn(day) -> None:
    """Ingest ESPN scoreboard + box scores for one date."""
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with EspnClient(settings) as client:
            click.echo(sync_date(db, client, day.date()))
    finally:
        db.close()


@cli.command("backfill-espn")
@click.option("--since", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--until", type=click.DateTime(["%Y-%m-%d"]), default=str(date.today()))
def backfill_espn(since, until) -> None:
    """Ingest ESPN data for every date in [since, until]."""
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with EspnClient(settings) as client:
            click.echo(backfill(db, client, since.date(), until.date()))
    finally:
        db.close()


@cli.command("sync-recent")
@click.option(
    "--days",
    default=3,
    show_default=True,
    help="Re-ingest a trailing window ending today, to pick up score/status corrections.",
)
@click.option(
    "--days-ahead",
    default=7,
    show_default=True,
    help="Also ingest scheduled games this many days into the future.",
)
def sync_recent(days: int, days_ahead: int) -> None:
    """Ingest ESPN data for a window around today.

    Meant for a recurring schedule (cron, launchd, ...): a short trailing
    window is cheap to re-sweep and catches games that were 'scheduled' on
    first ingest and have since gone final, without needing a full backfill.

    The window also leads today, because other parts of the system need a
    game to exist BEFORE it is played. The focused odds capture resolves
    each odds row to a `games` row and drops the ones it cannot place; when
    this swept backwards only, the schedule ended roughly at today and
    every book quote for a game further out was discarded with nothing but
    a WARNING in a launchd log. ESPN serves scheduled dates happily, so
    leading by a week costs one cheap request per day and removes the
    whole class of failure.
    """
    since = date.today() - timedelta(days=days)
    until = date.today() + timedelta(days=days_ahead)
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with EspnClient(settings) as client:
            click.echo(backfill(db, client, since, until))
    finally:
        db.close()


@cli.command("snapshot-kalshi")
@click.option("--series", "series_tickers", multiple=True, help="Limit to specific series.")
def snapshot_kalshi(series_tickers: tuple[str, ...]) -> None:
    """Snapshot current Kalshi WNBA market prices."""
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with KalshiClient(settings) as client:
            click.echo(
                ingest_kalshi_wnba_markets(db, client, series_tickers=series_tickers or None)
            )
    finally:
        db.close()


@cli.command("snapshot-injuries")
def snapshot_injuries() -> None:
    """Snapshot the current league-wide ESPN injury report.

    Current-state only -- see db/migrations/0005_injury_reports.sql. This
    only ever captures *today's* report; for real history see
    backfill-injuries-wayback.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with EspnClient(settings) as client:
            click.echo(ingest_current_injury_report(db, client))
    finally:
        db.close()


@cli.command("snapshot-balldontlie-injuries")
def snapshot_balldontlie_injuries() -> None:
    """Snapshot the current league-wide balldontlie injury report.

    A second live current-state source alongside ESPN's, for
    cross-validation -- see db/migrations/0016_balldontlie_injury_reports.sql.
    Current-state only, same as snapshot-injuries: this endpoint has no
    date/season filter, so there's no history to backfill.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(snapshot_current_injuries(db, client))
    finally:
        db.close()


@cli.command("backfill-injuries-wayback")
@click.option("--since", type=click.DateTime(["%Y-%m-%d"]), default="2022-04-01", show_default=True)
@click.option("--until", type=click.DateTime(["%Y-%m-%d"]), default=str(date.today()))
def backfill_injuries_wayback(since, until) -> None:
    """Backfill real historical injury status from archived ESPN pages.

    One Wayback Machine snapshot per day, ~1.5s apart out of courtesy to
    archive.org (a free, donation-funded service, not a commercial API) --
    this takes a while for a multi-year range. Resumable: an interrupted
    run picks back up without re-fetching already-captured days.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with WaybackClient(settings) as client:
            click.echo(backfill_injury_history(db, client, since.date(), until.date()))
    finally:
        db.close()


@cli.command("backfill-advanced-stats")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2024.")
def backfill_advanced_stats(season: int) -> None:
    """Backfill balldontlie advanced player stats for one season.

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY. Two
    phases: resolve balldontlie's games to our canonical games via
    team+date matching, then ingest per-player advanced stats using that
    crosswalk. Upserted, safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_season(db, client, season))
    finally:
        db.close()


@cli.command("backfill-team-advanced-stats")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2024.")
def backfill_team_advanced_stats(season: int) -> None:
    """Backfill balldontlie advanced team stats for one season.

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY. Two
    phases: resolve balldontlie's games to our canonical games via
    team+date matching, then ingest per-team advanced stats using that
    crosswalk. Upserted, safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_team_advanced_stats_season(db, client, season))
    finally:
        db.close()


@cli.command("backfill-balldontlie-stats")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2024.")
def backfill_balldontlie_stats(season: int) -> None:
    """Backfill balldontlie TRADITIONAL box score stats (points, rebounds,
    assists, etc.) for one season -- a second, independent source of the
    same stats ESPN's box scores already provide, for future cross-source
    validation.

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY. Not
    to be confused with backfill-advanced-stats (offensive/defensive
    rating, PIE, four factors -- data ESPN has no equivalent for). Writes
    into the SAME team_game_stats/player_game_stats tables ESPN populates,
    with source='balldontlie', via the same team+date game crosswalk and
    name-based player resolution backfill-advanced-stats uses. Upserted,
    safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_balldontlie_stats_season(db, client, season))
    finally:
        db.close()


@cli.command("backfill-plays")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2024.")
def backfill_plays(season: int) -> None:
    """Backfill balldontlie play-by-play for one season.

    Paid API (GOAT tier). One request per game (no cursor pagination on
    this endpoint); games resolve via the same crosswalk
    backfill-advanced-stats uses. No structured player attribution --
    plays carry a team and a free-text description only. Idempotent,
    safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_season_plays(db, client, season))
    finally:
        db.close()


@cli.command("backfill-shot-zones")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2024.")
def backfill_shot_zones(season: int) -> None:
    """Backfill balldontlie season-level shot-zone efficiency splits
    (player and team) for one season.

    Paid API (GOAT tier). Despite the source endpoint's name, this is NOT
    per-shot x/y coordinate data -- it's field goals attempted/made
    aggregated into 8 fixed court zones. Upserted, safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_season_shot_zones(db, client, season))
    finally:
        db.close()


@cli.command("backfill-players")
def backfill_players_cmd() -> None:
    """Sweep balldontlie's /wnba/v1/players endpoint for EVERY player it
    has ever recorded, regardless of season or recent game activity.

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY. No
    --season option: this is a global sweep, not scoped to one season.
    Backfills bio data (height/weight/jersey_number/college/age) for
    players the season-scoped advanced-stats/shot-zone pipelines never
    reach, via the same name-based crosswalk. Safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_players(db, client))
    finally:
        db.close()


@cli.command("backfill-standings")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2024.")
def backfill_standings(season: int) -> None:
    """Backfill balldontlie official standings for one season.

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY.
    Season-level only (no game dimension): fetches the season's current
    standings in a single request and resolves each row's team via
    find_team_by_abbreviation. Writes both team_standings (upserted --
    always reflects the latest fetch) and team_standings_history
    (append-only -- a new timestamped snapshot row per run, skipped only
    when unchanged since the last capture). Safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_standings_season(db, client, season))
    finally:
        db.close()


@cli.command("backfill-transactions")
@click.option("--since-season", type=int, required=True, help="First season year, e.g. 2022.")
@click.option("--until-season", type=int, required=True, help="Last season year, e.g. 2025.")
def backfill_transactions(since_season: int, until_season: int) -> None:
    """Backfill ESPN roster-move transactions (signings, waivers, releases,
    trades, front-office/coaching hires) for every season in
    [since-season, until-season].

    Free API, no key required. `description` is always stored verbatim;
    `transaction_type` and `player_id`/`raw_player_name` are best-effort
    extraction off that free text (see espn/transaction_classifier.py) and
    fall back to 'other'/NULL rather than blocking ingestion. Append-only,
    idempotent -- a re-run over an already-ingested season inserts nothing
    new (see db/migrations/0020_player_transactions.sql).
    """
    if since_season > until_season:
        raise click.UsageError(
            f"--since-season ({since_season}) must not be after --until-season ({until_season})"
        )
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with EspnClient(settings) as client:
            for season in range(since_season, until_season + 1):
                result = backfill_transactions_season(db, client, season)
                click.echo(f"season {season}: {result}")
    finally:
        db.close()


@cli.command("backfill-odds")
@click.option("--since", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--until", type=click.DateTime(["%Y-%m-%d"]), default=str(date.today()))
def backfill_odds(since, until) -> None:
    """Backfill balldontlie game-level sportsbook odds (moneyline/spread/
    total) for every date in [since, until].

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY. A
    genuinely different concept from snapshot-kalshi/snapshot-polymarket
    (real bookmaker odds, not peer-to-peer prediction-market contracts --
    see db/migrations/0014_balldontlie_odds.sql). Date-ranged, not
    --season, because the odds endpoint only carries a rolling recent
    window, not full historical archives. Append-only: a re-run over an
    unchanged window is a no-op; genuine line movement adds new rows.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_odds_date_range(db, client, since.date(), until.date()))
    finally:
        db.close()


@cli.command("backfill-player-prop-odds")
@click.option("--season", type=int, required=True, help="Season year, e.g. 2026.")
def backfill_player_prop_odds(season: int) -> None:
    """Backfill balldontlie player-prop sportsbook odds for one season.

    Paid API (GOAT tier) -- requires WNBA_ENGINE_BALLDONTLIE_API_KEY. Two
    phases: resolve balldontlie's games to our canonical games (same
    crosswalk backfill-advanced-stats uses), then query player-prop odds
    per game -- games with no cached props return empty, not an error.
    Players resolve via a straight crosswalk lookup only (this payload
    carries no player name), so a player never seen by another balldontlie
    pipeline is skipped. Append-only, same as backfill-odds.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with BalldontlieClient(settings) as client:
            click.echo(backfill_player_prop_odds_season(db, client, season))
    finally:
        db.close()


@cli.command("snapshot-polymarket")
def snapshot_polymarket() -> None:
    """Snapshot current Polymarket WNBA market prices."""
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with PolymarketClient(settings) as client:
            click.echo(ingest_polymarket_wnba_markets(db, client))
    finally:
        db.close()


@cli.command("backfill-polymarket-trades")
@click.option(
    "--no-resume",
    "no_resume",
    is_flag=True,
    help="Re-fetch markets that already have stored fills (needed to pick up "
    "new trades on markets that are still open).",
)
@click.option("--limit", "market_limit", type=int, default=None, help="Cap markets processed.")
def backfill_polymarket_trades_cmd(no_resume: bool, market_limit: int | None) -> None:
    """Backfill every on-chain Polymarket fill for WNBA markets.

    REAL history, unlike snapshot-polymarket. The CLOB's price endpoint is a
    rolling ~30-day cache, but data-api serves every fill back to 2024-09-20
    -- so a market that resolved in June is still fully recoverable today.

    Each fill records the outcome as a team name, which the snapshot table
    cannot do: Gamma leaves groupItemTitle null on two-way game markets, so
    which side its probability describes has to be inferred there.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with PolymarketClient(settings) as gamma, PolymarketDataClient(settings) as data:
            click.echo(
                backfill_polymarket_trades(
                    db, gamma, data, resume=not no_resume, market_limit=market_limit
                )
            )
    finally:
        db.close()


@cli.command("backfill-kalshi-candles")
@click.option("--series", "series_tickers", multiple=True, help="Limit to specific series.")
@click.option(
    "--derivatives", is_flag=True,
    help="Sweep quarter/half totals and winners instead of the full-game series.",
)
@click.option(
    "--period",
    "period_minutes",
    type=click.Choice(["1", "60", "1440"]),
    default="60",
    show_default=True,
    help="Bar size. 1-minute is capped at a ~3-day request window, so a full "
    "sweep at that resolution costs ~50x the requests of hourly.",
)
@click.option("--limit", "market_limit", type=int, default=None, help="Cap markets per series.")
def backfill_kalshi_candles_cmd(
    series_tickers: tuple[str, ...], derivatives: bool,
    period_minutes: str, market_limit: int | None
) -> None:
    """Backfill Kalshi OHLC bars for WNBA game markets.

    Bars go back to market creation, so this is genuine history rather than
    a snapshot. Keeps yes_bid and yes_ask separately rather than a midpoint:
    the spread is how an empty book is told apart from a real quote, and
    empty books are what make a naive lead-lag study meaningless.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with KalshiClient(settings) as client:
            click.echo(
                backfill_kalshi_candles(
                    db,
                    client,
                    series=series_tickers or (DERIVATIVE_SERIES if derivatives else GAME_SERIES),
                    period_minutes=int(period_minutes),
                    market_limit=market_limit,
                )
            )
    finally:
        db.close()


@cli.command("lead-lag-report")
def lead_lag_report() -> None:
    """Measure whether Polymarket or the sportsbooks move first.

    The one hypothesis MODELING_FINDINGS.md lists as untested rather than
    refuted. It was untested because 30-minute quote snapshots cannot see a
    16-29 minute lag; polymarket_trades carries exact fill timestamps, so
    both sides are now event-timed.

    A lead is a NECESSARY condition for an edge, never a sufficient one --
    this repo already found one real price-direction signal (72.6%
    accuracy) that still lost money.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        report = build_lead_lag_report(db)
        click.echo(f"games with both venues: {report.games_considered}")
        for label, result in (
            ("polymarket -> books", report.polymarket_leads_books),
            ("books -> polymarket", report.books_lead_polymarket),
        ):
            click.echo(f"\n{label}  ({result.games} games)")
            for lag in result.by_lag:
                t = lead_lag_t(lag.correlation, lag.pairs)
                click.echo(
                    f"  lag {lag.lag_minutes:>+4}m  r={lag.correlation:>+7.4f}  "
                    f"n={lag.pairs:>7,}  t={t:>+7.2f}" if t is not None else
                    f"  lag {lag.lag_minutes:>+4}m  r={lag.correlation:>+7.4f}  n={lag.pairs:>7,}"
                )
            click.echo(
                f"  best: lag={result.best_lag_minutes}m r={result.best_correlation}"
            )
        click.echo("\ngame-clustered bootstrap (polymarket -> books, a priori lags):")
        for check in report.bootstrap:
            click.echo(
                f"  lag {check.lag_minutes:>+4}m  r={check.correlation}  "
                f"P(r<=0)={check.share_at_or_below_zero}  games={check.games}"
            )
    finally:
        db.close()


@cli.command("refresh-venue-prices")
@click.option("--series", "series_tickers", multiple=True, default=("KXWNBAGAME",),
              show_default=True, help="Kalshi series to refresh.")
def refresh_venue_prices(series_tickers: tuple[str, ...]) -> None:
    """Pull fresh fills for markets that have NOT settled yet.

    The divergence log reads `polymarket_trades` and `kalshi_trades`, and
    nothing was keeping them current: both tables are written by history
    backfills, so on 2026-08-05 the newest fill for any upcoming game was
    two days old and Kalshi had none at all. A detector with a ten-minute
    lookback can never fire against that.

    Only OPEN markets, on both venues. A settled market cannot trade again,
    so re-walking the archive every few minutes is pure cost -- and for
    Kalshi it is also the wrong tier entirely, since the historical tier
    serves what settled before the cutoff and cannot see tonight's game.

    Free on both venues (no metered quota), which is why this can run on
    the same two-minute cadence as the capture it feeds.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with PolymarketClient(settings) as gamma, PolymarketDataClient(settings) as data:
            pm = backfill_polymarket_trades(
                db, gamma, data, resume=False, open_only=True,
                close_within=timedelta(hours=48), require_game_match=True,
            )
            click.echo(f"polymarket: {pm}")
        with KalshiClient(settings) as kalshi:
            kx = backfill_kalshi_trades(
                db, kalshi, series=series_tickers, resume=False, live=True
            )
            click.echo(f"kalshi: {kx}")
    finally:
        db.close()


@cli.command("log-divergences")
@click.option("--window-hours", default=6, show_default=True,
              help="How long before tip-off a game becomes worth watching.")
@click.option("--lookback-minutes", default=10, show_default=True,
              help="Trailing window for the size-weighted venue price.")
@click.option("--min-volume", default=DEFAULT_MIN_VOLUME, show_default=True,
              help="Minimum venue volume in the lookback before it counts as priced.")
def log_divergences_cmd(window_hours: int, lookback_minutes: int, min_volume: float) -> None:
    """Record sportsbook prices that sit below prediction-market fair value.

    The forward half of the one strategy in MODELING_FINDINGS.md that
    survived every control. The effect is established (+0.97 pts CLV
    pooled); what history CANNOT show is whether the price is still there
    when you could act, because captures used to be 60 minutes apart and
    the move happens inside that gap.

    Meant to run right after each focused capture. Prints only when it
    finds something.

    Read-only price analysis; nothing here places a bet (see ROADMAP.md).
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        result = log_divergences(
            db,
            window=timedelta(hours=window_hours),
            lookback=timedelta(minutes=lookback_minutes),
            min_volume=min_volume,
        )
        if result.divergences_found:
            click.echo(result)
    finally:
        db.close()


@cli.command("divergence-report")
def divergence_report_cmd() -> None:
    """Read the divergence log as a paper-trade ledger.

    Split pre-tip from in-play and never pooled: in-play shows divergence
    four times as often and five times as large, which is either the real
    opportunity or exactly what a stale quote looks like. `survival` is
    what tells them apart.

    Judge on CLV, not ROI. CLV reaches t=3 in ~120 observations; ROI needs
    ~10,600, and simulating a genuine +1.94% edge at n=915 still shows a
    loss 28% of the time.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        click.echo(build_divergence_report(db))
    finally:
        db.close()


@cli.command("grade-divergences")
def grade_divergences_cmd() -> None:
    """Fill in whether each logged price survived, and its closing value.

    Two passes: `recheck` answers the executability question by asking
    whether the same book's next quote was still as good, and `closings`
    grades CLV once the game is final. Both only ever write into NULLs, so
    running this on any cadence is safe.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        click.echo(f"recheck:  {recheck_prices(db)}")
        click.echo(f"closings: {grade_closings(db)}")
    finally:
        db.close()


@cli.command("capture-odds-focused")
@click.option("--window-hours", default=6, show_default=True,
              help="How long before tip-off a game becomes worth watching.")
@click.option("--min-fills", default=DEFAULT_MIN_FILLS, show_default=True,
              help="Minimum Polymarket fills on a game before it is watched.")
def capture_odds_focused(window_hours: int, min_fills: int) -> None:
    """High-frequency sportsbook capture near tip-off.

    Answers ONE question, from MODELING_FINDINGS.md: when Polymarket moves,
    is the book's old price still there? Our normal captures are 60 minutes
    apart and the follow-through lands inside that gap, so the economics of
    the cross-venue lead cannot currently be tested.

    Spends ZERO requests unless a game is inside the window, and exactly one
    when there is -- the-odds-api bills /odds per market and region, not per
    event. The --min-fills gate is off by default; see DEFAULT_MIN_FILLS for
    why it stopped being a default.

    Prints only when it actually captures. On the two-minute schedule this
    runs ~720 times a day and nearly all of them are skips, which would bury
    the real entries in the launchd log. Check liveness with
    `launchctl print gui/$(id -u)/com.ostepan.wnba-odds-focused`, not by
    looking for a heartbeat here.

    Read-only price capture. This is not a trading system; see ROADMAP.md.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with OddsApiClient(settings) as client:
            result = capture_focused_odds(
                db,
                client,
                window=timedelta(hours=window_hours),
                min_fills=min_fills,
            )
            if result.skipped_reason is None:
                click.echo(result)
    finally:
        db.close()


@cli.command("backfill-kalshi-trades")
@click.option("--series", "series_tickers", multiple=True, default=("KXWNBAGAME",),
              show_default=True, help="Series to sweep.")
@click.option("--before", type=click.DateTime(["%Y-%m-%d"]), default=None,
              help="Only markets closing before this date (e.g. 2026-01-01 for 2025 only).")
@click.option("--no-resume", is_flag=True, help="Re-fetch markets already stored.")
@click.option("--limit", "market_limit", type=int, default=None)
def backfill_kalshi_trades_cmd(series_tickers, before, no_resume, market_limit) -> None:
    """Backfill Kalshi trades from the HISTORICAL tier.

    Kalshi splits its data at a cutoff and serves older markets only from
    /historical/*. Every other Kalshi command here reads the live tier and
    therefore cannot see anything settled before 2026-06-05 -- which for
    KXWNBAGAME means the whole 2025 season, including the Finals.

    That season is the out-of-sample year MODELING_FINDINGS.md says the
    Kalshi analysis lacks, so `--before 2026-01-01` is the interesting run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with KalshiClient(settings) as client:
            click.echo(
                backfill_kalshi_trades(
                    db, client,
                    series=series_tickers,
                    resume=not no_resume,
                    before=before.replace(tzinfo=UTC) if before else None,
                    market_limit=market_limit,
                )
            )
    finally:
        db.close()


@cli.command("ingest-wnba-stats")
@click.option("--season", "seasons", multiple=True, type=int, required=True,
              help="Season start year; repeatable (e.g. --season 2025 --season 2026).")
@click.option("--no-shots", is_flag=True, help="Plays only, skip the shot chart.")
@click.option("--no-resume", is_flag=True, help="Re-fetch games already ingested.")
@click.option("--limit", "game_limit", type=int, default=None, help="Cap games per season.")
def ingest_wnba_stats(seasons, no_shots, no_resume, game_limit) -> None:
    """Ingest player-attributed plays and shot locations from stats.wnba.com.

    The league's own feed, and the only source here that puts a PLAYER on a
    play -- FEATURE_ROADMAP.md ss9 lists player-level play-by-play as
    blocked because balldontlie publishes none. It also carries shot
    coordinates, and it goes back to 1997.

    Plays land in game_plays under source='wnba_stats', beside the
    balldontlie rows rather than replacing them.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with WnbaStatsClient(settings) as client:
            for season in seasons:
                click.echo(
                    ingest_wnba_stats_season(
                        db, client, season,
                        resume=not no_resume,
                        include_shots=not no_shots,
                        game_limit=game_limit,
                    )
                )
    finally:
        db.close()


@cli.command("relink-market-games")
@click.option("--dry-run", is_flag=True, help="Report what would link, write nothing.")
def relink_market_games(dry_run: bool) -> None:
    """Fill NULL game_id on stored prediction-market snapshots.

    ON CONFLICT DO NOTHING makes every ingest re-runnable but also means a
    re-ingest cannot repair a row already stored -- so a matcher fix only
    helps rows written after it. Run this after changing any market/game
    matcher. Never overwrites a game_id that is already set.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        click.echo(relink_market_snapshots(db, dry_run=dry_run))
    finally:
        db.close()


@cli.command("ingest-market-captures")
@click.option(
    "--dir",
    "directory",
    default="~/wnba-market-capture",
    show_default=True,
    help="Capture root, containing kalshi/ and polymarket/ subdirectories.",
)
@click.option(
    "--all",
    "replay_all",
    is_flag=True,
    help="Re-read the whole archive, ignoring the already-ingested high-water mark.",
)
def ingest_market_captures_cmd(directory: str, replay_all: bool) -> None:
    """Load raw Kalshi/Polymarket captures recorded on the always-on host.

    Replays each captured payload through the same pipeline a live
    snapshot uses, stamped with the file's OWN capture time rather than
    now -- so a file recorded three days ago lands in the time series
    where it actually belongs.

    Idempotent: files older than what's already stored are skipped, and
    (provider, market_external_id, captured_at) is UNIQUE, so re-running
    after an interrupted sync inserts nothing new. Use --all to rebuild
    the archive through an improved parser.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        click.echo(
            ingest_captures(db, Path(directory).expanduser(), replay_all=replay_all)
        )
    finally:
        db.close()


@cli.command("snapshot-odds-api")
def snapshot_odds_api() -> None:
    """Snapshot current the-odds-api sportsbook odds (moneyline/spread/
    total) for every currently-listed WNBA event.

    Paid API (high-quota plan) -- requires WNBA_ENGINE_ODDS_API_KEY. Writes
    into the SAME sportsbook_game_odds table balldontlie's odds pipeline
    uses, with source='the_odds_api' (see
    db/migrations/0014_balldontlie_odds.sql). Games resolve via the same
    team+date crosswalk pattern Kalshi/Polymarket/balldontlie use.
    Append-only but idempotent: UNIQUE(external_id, captured_at) makes an
    unchanged re-run a no-op.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with OddsApiClient(settings) as client:
            click.echo(snapshot_odds_api_odds(db, client))
    finally:
        db.close()


@cli.command("backfill-odds-api-history")
@click.option("--since", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--until", type=click.DateTime(["%Y-%m-%d"]), default=str(date.today()))
def backfill_odds_api_history_cmd(since, until) -> None:
    """Backfill REAL historical the-odds-api odds for every canonical game
    in [since, until] (games.start_time), at T-7d/T-24h/T-1h/closing
    checkpoints per game (matching the line-movement cadence ROADMAP.md
    documents for the private Phase 0 pipeline this is modeled on).

    Paid API (high-quota plan) -- requires WNBA_ENGINE_ODDS_API_KEY. A
    historical call costs ~10x a current-odds call (verified live) -- this
    is a manual/one-off command, not on the recurring schedule, same
    convention as balldontlie's --season backfills. Date-ranged over OUR
    games table, not a provider schedule, since checkpoints are computed
    per canonical game. Idempotent, safe to re-run.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with OddsApiClient(settings) as client:
            click.echo(backfill_odds_api_history(db, client, since.date(), until.date()))
    finally:
        db.close()


@cli.command("snapshot-odds-api-props")
def snapshot_odds_api_props_cmd() -> None:
    """Snapshot CURRENT the-odds-api player props for every listed event.

    Props are unavailable on the bulk odds endpoint this repo's game-level
    ingestion uses -- they exist only per-event, which is why
    sportsbook_player_prop_odds was balldontlie-only before this command.

    Costs 1 quota unit per market per event (5 markets requested), so a
    typical slate is tens of units, not thousands. Safe on a recurring
    schedule alongside snapshot-odds-api.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with OddsApiClient(settings) as client:
            click.echo(snapshot_odds_api_props(db, client))
    finally:
        db.close()


@cli.command("backfill-odds-api-props-history")
@click.option("--since", type=click.DateTime(["%Y-%m-%d"]), required=True)
@click.option("--until", type=click.DateTime(["%Y-%m-%d"]), default=str(date.today()))
def backfill_odds_api_props_history_cmd(since, until) -> None:
    """Backfill REAL historical player props for every canonical game in
    [since, until], at the same T-7d/T-24h/T-1h/closing checkpoints the
    game-odds backfill uses.

    EXPENSIVE -- the most quota-hungry command in this repo. Historical
    props cost 10 units per market per event per checkpoint, so with 5
    markets and 4 checkpoints that is ~200 units per game (a full
    2023-present sweep is ~209k units). The result's units_estimated can
    be reconciled against the-odds-api's x-requests-used header.

    Props only exist in the archive from May 2023 -- earlier ranges return
    nothing (featured markets go back to May 2022, props do not). Requires
    backfill-odds-api-history to have run first for the same range: event
    ids come from provider_entity_map rather than a paid event-list call,
    and games without one are skipped and reported.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with OddsApiClient(settings) as client:
            click.echo(backfill_odds_api_props_history(db, client, since.date(), until.date()))
    finally:
        db.close()


@cli.command("snapshot-odds-api-scores")
@click.option(
    "--days-from",
    type=int,
    default=3,
    show_default=True,
    help="How many trailing days of completed games to check.",
)
def snapshot_odds_api_scores_cmd(days_from: int) -> None:
    """Snapshot the-odds-api's own final scores for recently-completed
    games -- a cross-check ONLY (see
    db/migrations/0021_odds_api_game_scores.sql and the
    odds_api_score_matches_game_score validation check). Never writes to
    games.home_score/away_score.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with OddsApiClient(settings) as client:
            click.echo(snapshot_odds_api_scores(db, client, days_from=days_from))
    finally:
        db.close()


@cli.command("build-features")
@click.option(
    "--as-of",
    type=click.DateTime(["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]),
    required=True,
    help="Point-in-time boundary. A bare date means 00:00 UTC on that date.",
)
@click.option(
    "--strategy",
    type=click.Choice(sorted(FEATURE_STRATEGIES)),
    default="situational_baseline",
    show_default=True,
)
@click.option(
    "--season",
    "seasons",
    type=int,
    multiple=True,
    help="Restrict to these seasons; repeatable. Omit for every season.",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the frame to CSV as well as printing the summary.",
)
@click.option("--show-columns", is_flag=True, help="List the produced column names.")
def build_features_cmd(as_of, strategy: str, seasons: tuple[int, ...], out, show_columns) -> None:
    """Build a point-in-time-correct feature frame.

    `--as-of` is the instant beyond which NO data may be used. Everything
    the strategy loads is filtered to it, and every step's output is
    re-checked against it afterwards (see wnba_engine/features/guard.py),
    so a step that reads past the boundary fails loudly here rather than
    producing a model that backtests well and cannot be reproduced live.

    Naive input is interpreted as UTC, matching the TIMESTAMPTZ columns
    this reads; --as-of 2025-08-01 therefore means 2025-08-01T00:00:00Z.

    Note the boundary is stricter than it looks for game data: `games`
    records when a game STARTED, not when its result became known, so
    loaders additionally require the game to have finished a few hours
    before the boundary (wnba_engine/features/steps/loading.py).
    """
    context = FeatureContext(
        as_of=as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of,
        seasons=tuple(seasons),
    )
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        build = build_features(db, strategy=strategy, context=context, output_path=out)
    finally:
        db.close()

    click.echo(build.result)
    if show_columns:
        for column in build.frame.columns:
            click.echo(f"  {column}")


@cli.command("clv-report")
@click.option("--prop-type", "prop_types", multiple=True, help="Limit to specific prop types.")
@click.option("--season", "seasons", multiple=True, type=int, help="Limit to specific seasons.")
def clv_report_cmd(prop_types: tuple[str, ...], seasons: tuple[int, ...]) -> None:
    """Measure how far prop prices drift between opening and closing.

    Reports the OPPORTUNITY, not a prediction's performance -- there is no
    predictor yet. Mean CLV near zero means the market has no systematic
    drift to farm; a non-trivial standard deviation means prices do move,
    so the target becomes predicting WHICH ones rather than betting a side.

    Scored from the under side by convention; over-side CLV is its exact
    negative. Prices are de-vigged first, so a book merely widening its
    margin does not register as the market changing its mind.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        click.echo(
            build_clv_report(db, prop_types=prop_types or None, seasons=seasons or None)
        )
    finally:
        db.close()


@cli.command("style-comps")
@click.option("--subject", type=click.Choice(["player", "team"]), default="player",
              show_default=True)
@click.option("--find", "query", help="Name substring, e.g. 'Collier 2025'.")
@click.option("--unique", is_flag=True, help="Rank by stylistic uniqueness instead.")
@click.option("--limit", default=5, show_default=True)
def style_comps_cmd(subject: str, query: str | None, unique: bool, limit: int) -> None:
    """Nearest comparables in style space, or the league's most unusual profiles.

    Style, deliberately not quality: player vectors are per-36 rates and
    shares, and team vectors exclude offensive/defensive rating, so a good
    and a bad team that play alike come out as neighbours. See
    wnba_engine/analysis/style.py.

    A player's own prior season showing up as her nearest comparable is
    the expected result and the best evidence the space means something;
    --unique excludes self-matches, since "nobody plays like her except
    her" would otherwise read as unremarkable.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        with db.connection() as conn:
            raw = (style_repo.load_player_points(conn) if subject == "player"
                   else style_repo.load_team_points(conn))
    finally:
        db.close()
    points = style_space.z_score(raw)
    click.echo(f"{len(points)} {subject}-seasons in {len(points[0].coordinates)}-dim style space")

    if unique:
        for point, dist in style_space.uniqueness(points)[:limit]:
            click.echo(f"  {dist:5.2f}  {point.label}")
        return
    if not query:
        raise click.UsageError("pass --find NAME, or --unique")
    matches = [p for p in points if query.lower() in p.label.lower()]
    if not matches:
        raise click.UsageError(f"no {subject} matching {query!r}")
    target = matches[0]
    click.echo(f"nearest to {target.label}:")
    for n in style_space.nearest(points, target, limit=limit):
        click.echo(f"  {n.distance:5.2f}  {n.point.label}")


@cli.command("validate")
def validate() -> None:
    """Run every data-quality check against the real database.

    Cross-source consistency (ESPN box score vs scoreboard, balldontlie
    plays vs ESPN score, ...), crosswalk integrity, and plausibility
    bounds -- see wnba_engine/validation/. Exits non-zero if any check
    fails, so this is safe to wire into a cron/CI gate later.

    Violations individually verified as known-benign (see
    wnba_engine/validation/acknowledged.py) are still counted and printed,
    marked [ack], but don't fail the run -- otherwise a permanently-red
    gate teaches everyone to ignore it. Anything NOT acknowledged still
    fails, so a new violation of an already-acknowledged check is loud.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        report = run_all_checks(db)
    finally:
        db.close()

    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        counts = f"{check.unacknowledged_count} violation(s)"
        if check.acknowledged_count:
            counts += f", {check.acknowledged_count} acknowledged"
        click.echo(f"[{status}] {check.name}: {counts}")
        click.echo(f"       {check.description}")
        for sample in check.sample_violations:
            click.echo(f"       - {sample}")
        for sample in check.sample_acknowledged:
            click.echo(f"       - [ack] {sample}")

    if report.stale_acknowledgements:
        click.echo("")
        click.echo(
            "Stale acknowledgements (no longer match any violation -- "
            "remove them from wnba_engine/validation/acknowledged.py):"
        )
        for entry in report.stale_acknowledgements:
            click.echo(f"  - {entry}")

    if not report.passed:
        sys.exit(1)


if __name__ == "__main__":
    cli()
