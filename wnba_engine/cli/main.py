"""Deliberately minimal CLI: migrate + one ingest command per provider.

Just enough to smoke-test the pipeline by hand; real CLI polish is a
separate, later task.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import click

from wnba_engine.balldontlie.client import BalldontlieClient
from wnba_engine.config import load_settings
from wnba_engine.db.migrate import run_migrations
from wnba_engine.db.pool import Database
from wnba_engine.espn.client import EspnClient
from wnba_engine.espn.wayback_client import WaybackClient
from wnba_engine.kalshi.client import KalshiClient
from wnba_engine.pipeline.balldontlie_advanced_stats_ingest import backfill_season
from wnba_engine.pipeline.balldontlie_plays_ingest import backfill_season_plays
from wnba_engine.pipeline.balldontlie_shot_zone_ingest import backfill_season_shot_zones
from wnba_engine.pipeline.espn_ingest import backfill, sync_date
from wnba_engine.pipeline.injury_ingest import ingest_current_injury_report
from wnba_engine.pipeline.kalshi_ingest import ingest_kalshi_wnba_markets
from wnba_engine.pipeline.polymarket_ingest import ingest_polymarket_wnba_markets
from wnba_engine.pipeline.wayback_injury_backfill import backfill_injury_history
from wnba_engine.polymarket.client import PolymarketClient


@click.group()
def cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


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
def sync_recent(days: int) -> None:
    """Ingest ESPN data for the last N days through today.

    Meant for a recurring schedule (cron, launchd, ...): a short trailing
    window is cheap to re-sweep and catches games that were 'scheduled' on
    first ingest and have since gone final, without needing a full backfill.
    """
    since = date.today() - timedelta(days=days)
    until = date.today()
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


if __name__ == "__main__":
    cli()
