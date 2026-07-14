"""Runs every registered data-quality check against the real database and
assembles a report. To add a check: write the function in the appropriate
checks module (crosswalk/consistency/bounds), then register it below.
"""

from __future__ import annotations

from collections.abc import Callable

from psycopg import Connection

from wnba_engine.db.pool import Database
from wnba_engine.models.validation import CheckResult, ValidationReport
from wnba_engine.validation import (
    bounds_checks,
    consistency_checks,
    crosswalk_checks,
    franchise_checks,
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
)


def run_all_checks(db: Database) -> ValidationReport:
    with db.connection() as conn:
        results = tuple(check(conn) for check in _CHECKS)
    return ValidationReport(checks=results)
