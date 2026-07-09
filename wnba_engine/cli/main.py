"""Deliberately minimal CLI: migrate + one ingest command per provider.

Just enough to smoke-test the pipeline by hand; real CLI polish is a
separate, later task.
"""

from __future__ import annotations

import logging
import sys
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
from wnba_engine.pipeline.espn_ingest import backfill, sync_date
from wnba_engine.pipeline.espn_transactions_ingest import (
    backfill_season as backfill_transactions_season,
)
from wnba_engine.pipeline.injury_ingest import ingest_current_injury_report
from wnba_engine.pipeline.kalshi_ingest import ingest_kalshi_wnba_markets
from wnba_engine.pipeline.polymarket_ingest import ingest_polymarket_wnba_markets
from wnba_engine.pipeline.wayback_injury_backfill import backfill_injury_history
from wnba_engine.polymarket.client import PolymarketClient
from wnba_engine.validation.runner import run_all_checks


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


@cli.command("validate")
def validate() -> None:
    """Run every data-quality check against the real database.

    Cross-source consistency (ESPN box score vs scoreboard, balldontlie
    plays vs ESPN score, ...), crosswalk integrity, and plausibility
    bounds -- see wnba_engine/validation/. Exits non-zero if any check
    fails, so this is safe to wire into a cron/CI gate later.
    """
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        report = run_all_checks(db)
    finally:
        db.close()

    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        click.echo(f"[{status}] {check.name}: {check.violation_count} violation(s)")
        click.echo(f"       {check.description}")
        for sample in check.sample_violations:
            click.echo(f"       - {sample}")

    if not report.passed:
        sys.exit(1)


if __name__ == "__main__":
    cli()
