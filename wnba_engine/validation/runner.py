"""Runs every registered data-quality check against the real database and
assembles a report. To add a check: write the function in the appropriate
checks module (crosswalk/consistency/bounds), then register it below.
"""

from __future__ import annotations

from collections.abc import Callable

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.models.validation import CheckResult, ValidationReport
from wnba_engine.validation import acknowledged as ack
from wnba_engine.validation import (
    bounds_checks,
    consistency_checks,
    crosswalk_checks,
    franchise_checks,
    market_history_checks,
)

_CHECKS: tuple[Callable[[Connection], CheckResult], ...] = (
    crosswalk_checks.check_orphaned_crosswalk_entries,
    crosswalk_checks.check_duplicate_crosswalk_mappings,
    consistency_checks.check_team_box_score_matches_final_score,
    consistency_checks.check_team_totals_match_player_sums,
    consistency_checks.check_plays_final_score_matches_game_score,
    consistency_checks.check_odds_api_score_matches_game_score,
    bounds_checks.check_team_stat_bounds,
    bounds_checks.check_player_stat_bounds,
    bounds_checks.check_market_price_bounds,
    bounds_checks.check_player_shot_zone_bounds,
    bounds_checks.check_team_shot_zone_bounds,
    franchise_checks.check_non_franchise_team_in_regular_season,
    franchise_checks.check_regular_season_game_counts,
    market_history_checks.check_polymarket_trade_bounds,
    market_history_checks.check_kalshi_candle_bounds,
    market_history_checks.check_kalshi_book_is_not_crossed,
    market_history_checks.check_no_trade_long_after_settlement,
)


def find_stale_acknowledgements(results: tuple[CheckResult, ...]) -> tuple[str, ...]:
    """Acknowledgements that matched no violation on this run.

    Every registered check runs every time, so an entry whose key went
    unmatched means the underlying violation is gone -- fixed upstream,
    or the data changed shape. Either way the entry is dead weight, and
    surfacing it keeps acknowledged.py from rotting into a list of
    things that stopped being true. Reported, never auto-removed:
    dropping an acknowledgement is a human decision.
    """
    matched = {key for result in results for key in result.matched_acknowledgements}
    return tuple(
        f"{entry.check_name}: {entry.key} ({entry.reason})"
        for entry in ack.ACKNOWLEDGEMENTS
        if entry.key not in matched
    )


def run_all_checks(db: Database) -> ValidationReport:
    with db.connection() as conn:
        results = tuple(check(conn) for check in _CHECKS)
    return ValidationReport(
        checks=results,
        stale_acknowledgements=find_stale_acknowledgements(results),
    )
