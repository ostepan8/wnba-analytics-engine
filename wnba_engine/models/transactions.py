"""ESPN transactions feed shape (roster moves: signings, waivers, releases,
trades, activations, front-office/coaching hires, ...).

No structured player field -- see espn/transactions_parser.py module
docstring. RawTransaction is deliberately just "what ESPN sent" (date,
free-text description, team) with no interpretation; best-effort
type/player extraction from the description text is a separate concern
(see espn/transaction_classifier.py) applied downstream in the ingest
pipeline, not baked into this parse step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawTransaction:
    transaction_date: datetime
    description: str
    team_external_id: str
    team_name: str
