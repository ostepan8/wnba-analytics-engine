"""Pure parsers: stats.wnba.com resultSets -> validated domain models.

The API returns a column-oriented shape rather than objects:

    {"resultSets": [{"name": ..., "headers": [...], "rowSet": [[...], ...]}]}

`_rows` turns that back into dicts by zipping headers to values, which is
worth doing once here rather than by index at every call site: the column
ORDER is not part of any contract and has changed on the NBA side before,
so positional access is a silent-corruption risk.

Verified live on 2026-08-04 against LeagueID=10, seasons 1997-2026.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from wnba_engine.errors import ProviderValidationError
from wnba_engine.parsing import optional_int, optional_str

PROVIDER = "wnba_stats"

#: PERSONnTYPE values that mean the slot holds a PLAYER. 2 and 3 mean it
#: holds a TEAM, and when it does the id in PLAYERn_ID is a team id
#: (1611661xxx) with a null name -- team rebounds, timeouts, delay-of-game.
#:
#: Reading the id without checking the type maps 8% of attributed events to
#: a "player" who is actually a franchise: 27 of 341 in the first game
#: examined. It would not error, it would resolve to nothing or, worse, to
#: whatever entity happened to carry that external id.
PLAYER_PERSON_TYPES = frozenset({4, 5})
TEAM_PERSON_TYPES = frozenset({2, 3})

#: EVENTMSGTYPE -> a human label, so `game_plays.play_type` carries the
#: same kind of value balldontlie writes there rather than a bare integer.
#: The numeric code is kept alongside it in `event_type`: the label is for
#: reading, the code is what a query should filter on, because the mapping
#: is ours and could be extended while the codes are the provider's.
EVENT_TYPE_LABELS: dict[int, str] = {
    1: "Made Shot",
    2: "Missed Shot",
    3: "Free Throw",
    4: "Rebound",
    5: "Turnover",
    6: "Foul",
    7: "Violation",
    8: "Substitution",
    9: "Timeout",
    10: "Jump Ball",
    11: "Ejection",
    12: "Period Begin",
    13: "Period End",
    18: "Instant Replay",
}


def event_label(event_type: int | None) -> str:
    """A label for an EVENTMSGTYPE, never null.

    `game_plays.play_type` is NOT NULL, and an unmapped code is more
    useful rendered as "Event 19" than rejected -- the row still carries
    its description, participants and numeric type.
    """
    if event_type is None:
        return "Unknown"
    return EVENT_TYPE_LABELS.get(event_type, f"Event {event_type}")


@dataclass(frozen=True, slots=True)
class StatsGameRef:
    """One team's row in the league game log."""

    game_id: str
    game_date: date
    team_abbreviation: str
    matchup: str
    season: int

    @property
    def is_home(self) -> bool:
        """MATCHUP reads 'CHI vs. NYL' at home and 'CHI @ NYL' away."""
        return " vs. " in self.matchup


@dataclass(frozen=True, slots=True)
class StatsPlay:
    """One play-by-play event, with participant ids."""

    game_id: str
    event_num: int
    event_type: int | None
    event_action_type: int | None
    period: int | None
    clock: str | None
    description: str | None
    score: str | None
    player1_external_id: str | None
    player2_external_id: str | None
    player3_external_id: str | None
    player1_name: str | None
    player2_name: str | None
    player3_name: str | None
    team_external_id: str | None


@dataclass(frozen=True, slots=True)
class StatsShot:
    """One shot attempt with court coordinates."""

    game_id: str
    game_event_id: int
    player_external_id: str | None
    player_name: str | None
    team_external_id: str | None
    period: int | None
    seconds_remaining: int | None
    action_type: str | None
    shot_type: str | None
    shot_zone_basic: str | None
    shot_zone_area: str | None
    shot_zone_range: str | None
    shot_distance: int | None
    loc_x: int | None
    loc_y: int | None
    made: bool


def _result_set(payload: object, name: str | None = None) -> Iterator[Mapping[str, object]]:
    """Yield dict rows from a named resultSet (or the first one)."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"payload must be an object, got {type(payload).__name__}"
        )
    sets = payload.get("resultSets")
    if not isinstance(sets, Sequence) or not sets:
        raise ProviderValidationError(PROVIDER, "payload has no resultSets")
    chosen = None
    for entry in sets:
        if not isinstance(entry, Mapping):
            continue
        if name is None or entry.get("name") == name:
            chosen = entry
            break
    if chosen is None:
        raise ProviderValidationError(PROVIDER, f"no resultSet named {name!r}")
    headers = chosen.get("headers")
    rows = chosen.get("rowSet")
    if not isinstance(headers, Sequence) or not isinstance(rows, Sequence):
        raise ProviderValidationError(PROVIDER, "resultSet is missing headers or rowSet")
    for row in rows:
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            yield dict(zip(headers, row, strict=False))


def parse_game_log(payload: object, *, season: int) -> tuple[StatsGameRef, ...]:
    """Two rows per game, one per team."""
    out: list[StatsGameRef] = []
    for row in _result_set(payload, "LeagueGameLog"):
        game_id = optional_str(row.get("GAME_ID"), PROVIDER, "GAME_ID")
        raw_date = optional_str(row.get("GAME_DATE"), PROVIDER, "GAME_DATE")
        abbrev = optional_str(row.get("TEAM_ABBREVIATION"), PROVIDER, "TEAM_ABBREVIATION")
        matchup = optional_str(row.get("MATCHUP"), PROVIDER, "MATCHUP")
        if not game_id or not raw_date or not abbrev or not matchup:
            continue
        try:
            parsed = date.fromisoformat(raw_date[:10])
        except ValueError as exc:
            raise ProviderValidationError(
                PROVIDER, f"unparseable GAME_DATE {raw_date!r}"
            ) from exc
        out.append(StatsGameRef(game_id, parsed, abbrev, matchup, season))
    return tuple(out)


def parse_play_by_play(payload: object) -> tuple[StatsPlay, ...]:
    """Events, keeping all three participant slots.

    The three slots are NOT interchangeable: 1 is the actor, 2 the
    secondary participant (assister on a make, shooter on a block), 3 a
    third party. Flattening them would discard the relationship that makes
    this source worth having over the play text alone.

    Description is assembled from HOME/VISITOR/NEUTRAL, exactly one of
    which is populated per event.
    """
    out: list[StatsPlay] = []
    for row in _result_set(payload, "PlayByPlay"):
        game_id = optional_str(row.get("GAME_ID"), PROVIDER, "GAME_ID")
        event_num = optional_int(row.get("EVENTNUM"), PROVIDER, "EVENTNUM")
        if not game_id or event_num is None:
            continue
        description = next(
            (
                text
                for key in ("HOMEDESCRIPTION", "VISITORDESCRIPTION", "NEUTRALDESCRIPTION")
                for text in [optional_str(row.get(key), PROVIDER, key)]
                if text
            ),
            None,
        )
        out.append(
            StatsPlay(
                game_id=game_id,
                event_num=event_num,
                event_type=optional_int(row.get("EVENTMSGTYPE"), PROVIDER, "EVENTMSGTYPE"),
                event_action_type=optional_int(
                    row.get("EVENTMSGACTIONTYPE"), PROVIDER, "EVENTMSGACTIONTYPE"
                ),
                period=optional_int(row.get("PERIOD"), PROVIDER, "PERIOD"),
                clock=optional_str(row.get("PCTIMESTRING"), PROVIDER, "PCTIMESTRING"),
                description=description,
                score=optional_str(row.get("SCORE"), PROVIDER, "SCORE"),
                player1_external_id=_participant(row, 1, PLAYER_PERSON_TYPES),
                player2_external_id=_participant(row, 2, PLAYER_PERSON_TYPES),
                player3_external_id=_participant(row, 3, PLAYER_PERSON_TYPES),
                # The acting team: named directly on a player event, or the
                # slot-1 id itself when slot 1 IS a team.
                player1_name=_participant_name(row, 1),
                player2_name=_participant_name(row, 2),
                player3_name=_participant_name(row, 3),
                team_external_id=(
                    _external(row.get("PLAYER1_TEAM_ID"))
                    or _participant(row, 1, TEAM_PERSON_TYPES)
                ),
            )
        )
    return tuple(out)


def parse_shot_chart(payload: object) -> tuple[StatsShot, ...]:
    """One row per attempt, with coordinates."""
    out: list[StatsShot] = []
    for row in _result_set(payload, "Shot_Chart_Detail"):
        game_id = optional_str(row.get("GAME_ID"), PROVIDER, "GAME_ID")
        event_id = optional_int(row.get("GAME_EVENT_ID"), PROVIDER, "GAME_EVENT_ID")
        made = row.get("SHOT_MADE_FLAG")
        if not game_id or event_id is None or made is None:
            continue
        minutes = optional_int(row.get("MINUTES_REMAINING"), PROVIDER, "MINUTES_REMAINING")
        seconds = optional_int(row.get("SECONDS_REMAINING"), PROVIDER, "SECONDS_REMAINING")
        out.append(
            StatsShot(
                game_id=game_id,
                game_event_id=event_id,
                player_external_id=_external(row.get("PLAYER_ID")),
                player_name=optional_str(row.get("PLAYER_NAME"), PROVIDER, "PLAYER_NAME"),
                team_external_id=_external(row.get("TEAM_ID")),
                period=optional_int(row.get("PERIOD"), PROVIDER, "PERIOD"),
                seconds_remaining=(
                    None if minutes is None or seconds is None else minutes * 60 + seconds
                ),
                action_type=optional_str(row.get("ACTION_TYPE"), PROVIDER, "ACTION_TYPE"),
                shot_type=optional_str(row.get("SHOT_TYPE"), PROVIDER, "SHOT_TYPE"),
                shot_zone_basic=optional_str(
                    row.get("SHOT_ZONE_BASIC"), PROVIDER, "SHOT_ZONE_BASIC"
                ),
                shot_zone_area=optional_str(
                    row.get("SHOT_ZONE_AREA"), PROVIDER, "SHOT_ZONE_AREA"
                ),
                shot_zone_range=optional_str(
                    row.get("SHOT_ZONE_RANGE"), PROVIDER, "SHOT_ZONE_RANGE"
                ),
                shot_distance=optional_int(row.get("SHOT_DISTANCE"), PROVIDER, "SHOT_DISTANCE"),
                loc_x=optional_int(row.get("LOC_X"), PROVIDER, "LOC_X"),
                loc_y=optional_int(row.get("LOC_Y"), PROVIDER, "LOC_Y"),
                made=bool(made),
            )
        )
    return tuple(out)


def _participant(row: Mapping[str, object], slot: int, wanted: frozenset[int]) -> str | None:
    """The id in `slot`, but only when PERSONnTYPE says it is the right kind.

    See PLAYER_PERSON_TYPES. Without the type check a team rebound files
    the franchise id as the rebounder.
    """
    kind = optional_int(row.get(f"PERSON{slot}TYPE"), PROVIDER, f"PERSON{slot}TYPE")
    if kind not in wanted:
        return None
    return _external(row.get(f"PLAYER{slot}_ID"))


def _participant_name(row: Mapping[str, object], slot: int) -> str | None:
    """The name for a slot, only when that slot holds a player.

    Carried alongside the id because resolution goes through
    provider_entity_map by NAME on first sight -- stats.wnba.com ids are a
    fourth id space and nothing in this database maps them yet.
    """
    kind = optional_int(row.get(f"PERSON{slot}TYPE"), PROVIDER, f"PERSON{slot}TYPE")
    if kind not in PLAYER_PERSON_TYPES:
        return None
    return optional_str(row.get(f"PLAYER{slot}_NAME"), PROVIDER, f"PLAYER{slot}_NAME")


def _external(value: object) -> str | None:
    """Provider ids as STRINGS, and 0 as absent.

    The feed uses 0 for "no participant in this slot" rather than null, so
    a naive read would map thousands of events to a player id of zero and
    then fail to resolve it -- or worse, resolve it to whatever entity
    happened to be numbered 0. Strings because provider_entity_map keys on
    text and every other provider here is already stored that way.
    """
    if value in (None, 0, "0", ""):
        return None
    return str(value)
