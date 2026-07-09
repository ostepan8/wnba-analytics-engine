"""Pure parser: raw ESPN transactions JSON -> RawTransaction. No network, no
DB, no free-text interpretation (see transaction_classifier.py for that).

Transactions payload shape (.../transactions?season=YYYY&limit=200&page=N):
  count, pageCount, pageIndex,
  transactions[] -> date, description, team{id, displayName, ...}

Deliberately thin: this module only extracts the three reliable, structured
fields ESPN actually sends (date, description, team) -- everything else
(transaction type, player identity) lives in the free-text `description`
and is handled downstream as best-effort interpretation, never here.
"""

from __future__ import annotations

from collections.abc import Mapping

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.transactions import RawTransaction
from wnba_engine.parsing import (
    parse_datetime_utc,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "espn"


def parse_transactions_page(payload: object) -> tuple[RawTransaction, ...]:
    """Parse one page of the transactions response into RawTransaction
    rows. Returns an empty tuple for a page with no transactions (last page
    of a multi-page season can legitimately be short/empty), rather than
    raising -- an empty `transactions[]` is a valid shape, not malformed.
    """
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"transactions payload must be an object, got {type(payload).__name__}"
        )
    raw_transactions = payload.get("transactions")
    if raw_transactions is None:
        return ()
    entries = require_sequence(payload, "transactions", PROVIDER, "transactions")
    return tuple(_parse_transaction(entry, f"transactions[{i}]") for i, entry in enumerate(entries))


def page_count(payload: object) -> int:
    """Total page count for this season, per ESPN's own `pageCount` field.

    Defaults to 1 if the field is missing/malformed -- fail open, same
    spirit as the enrichment fields in parser.py::_parse_game_info -- a
    caller should still get the one page it successfully fetched rather
    than aborting the whole backfill over a missing pagination hint.
    """
    if not isinstance(payload, Mapping):
        return 1
    value = payload.get("pageCount")
    return value if isinstance(value, int) and value >= 1 else 1


def _parse_transaction(entry: object, context: str) -> RawTransaction:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "transaction must be an object", context=context)
    transaction_date = parse_datetime_utc(
        require(entry, "date", PROVIDER, context), PROVIDER, f"{context}.date"
    )
    description = require_str(entry, "description", PROVIDER, context)
    team = require_mapping(entry, "team", PROVIDER, context)
    team_external_id = require_str(team, "id", PROVIDER, f"{context}.team")
    team_name = require_str(team, "displayName", PROVIDER, f"{context}.team")
    return RawTransaction(
        transaction_date=transaction_date,
        description=description,
        team_external_id=team_external_id,
        team_name=team_name,
    )
