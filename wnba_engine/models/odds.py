"""balldontlie sportsbook odds (currently balldontlie-only).

IMPORTANT -- this repo has TWO different "odds" concepts, and they are not
interchangeable:

1. `market_price_snapshots` (see db/migrations/0003_market_price_snapshots.sql)
   holds Kalshi/Polymarket PREDICTION-MARKET data: peer-to-peer yes/no
   contracts traded on an order book, where the "price" (0-1) already IS an
   implied probability.
2. The rows here (`GameOddsRow` / `PlayerPropOddsRow`, from balldontlie's
   /wnba/v1/odds and /wnba/v1/odds/player_props) are traditional SPORTSBOOK
   odds: moneyline/spread/total lines quoted by a real bookmaker (DraftKings,
   FanDuel, ...), in American odds format (e.g. -120, +900), not
   probabilities and not a peer-to-peer market.

Forcing these into one schema would be wrong -- different market structure,
different units, different semantics -- so they get their own tables (see
db/migrations/0014_balldontlie_odds.sql for the schema and why it's
append-only).

balldontlie identifies games/players with its own numeric ids -- these refs
carry balldontlie's raw external ids, resolved to canonical games/players via
the same provider_entity_map crosswalk every other balldontlie pipeline uses
(entity_repo.lookup_internal_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GameOddsRow:
    """One bookmaker's moneyline/spread/total line for one game, as of
    `updated_at` (balldontlie's own last-refreshed timestamp for this row --
    used as captured_at, not our own ingest wall-clock; see the migration
    for why).
    """

    external_id: str  # balldontlie's own odds-row id
    game_external_id: str  # balldontlie's own game id
    vendor: str  # 'draftkings' | 'fanduel' | 'fanatics' | 'caesars' | 'betmgm' | 'betrivers' | ...

    spread_home_value: float | None
    spread_home_odds: int | None
    spread_away_value: float | None
    spread_away_odds: int | None

    moneyline_home_odds: int | None
    moneyline_away_odds: int | None

    total_value: float | None
    total_over_odds: int | None
    total_under_odds: int | None

    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PlayerPropOddsRow:
    """One bookmaker's line for one player prop, as of `updated_at`.

    balldontlie's payload carries two distinct market shapes under the same
    `prop_type` (e.g. "points"), disambiguated by `market_type` (verified
    live -- confirmed in the same response, not different endpoints):

    - "milestone": a single-sided line ("will this player reach N?") with
      one `odds` value. `over_odds`/`under_odds` are None here.
    - "over_under": a two-sided line with both `over_odds` and `under_odds`.
      `odds` is None here.

    Both shapes are stored in one table with all three odds columns
    nullable, rather than two separate prop tables, since they share every
    other field (player, prop_type, line_value, vendor) and differ only in
    how many sides of the line are quoted.
    """

    external_id: str
    game_external_id: str
    player_external_id: str
    vendor: str
    prop_type: str  # 'points' | 'rebounds' | 'assists' | ... | 'double_double' | 'triple_double'
    line_value: float
    market_type: str  # 'milestone' | 'over_under'
    odds: int | None
    over_odds: int | None
    under_odds: int | None
    updated_at: datetime
