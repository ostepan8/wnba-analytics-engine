"""Pure parsers: raw ESPN JSON -> validated domain models. No network, no DB.

Scoreboard payload shape (site.api.espn.com .../scoreboard?dates=YYYYMMDD):
  events[] -> id, date, season.year, status.type.name,
              competitions[0].competitors[] (id, homeAway, score, team{...})

Summary payload shape (.../summary?event=<id>):
  header.id, boxscore.teams[] (team + statistics[] of named totals),
  boxscore.players[] (one per team; statistics[0].labels positionally
  aligned with each athlete's stats[] array).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from wnba_engine.errors import ProviderValidationError
from wnba_engine.models.box_scores import (
    GameBoxScore,
    PlayerBoxLine,
    PlayerRef,
    ShootingLine,
    TeamBoxScore,
)
from wnba_engine.models.games import GameStatus, ScoreboardGame, TeamRef
from wnba_engine.parsing import (
    optional_int,
    parse_datetime_utc,
    parse_int,
    require,
    require_mapping,
    require_sequence,
    require_str,
)

PROVIDER = "espn"

_STATUS_MAP = {
    "STATUS_SCHEDULED": GameStatus.SCHEDULED,
    "STATUS_IN_PROGRESS": GameStatus.IN_PROGRESS,
    "STATUS_HALFTIME": GameStatus.IN_PROGRESS,
    "STATUS_END_PERIOD": GameStatus.IN_PROGRESS,
    "STATUS_FINAL": GameStatus.FINAL,
}

# ESPN box score player stat labels, in the order stats[] is aligned to.
EXPECTED_PLAYER_LABELS = (
    "MIN", "PTS", "FG", "3PT", "FT", "REB", "AST",
    "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-",
)  # fmt: skip

_TEAM_STAT_NAMES = {
    "field_goals": "fieldGoalsMade-fieldGoalsAttempted",
    "three_pointers": "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
    "free_throws": "freeThrowsMade-freeThrowsAttempted",
    "rebounds": "totalRebounds",
    "offensive_rebounds": "offensiveRebounds",
    "defensive_rebounds": "defensiveRebounds",
    "assists": "assists",
    "steals": "steals",
    "blocks": "blocks",
    "turnovers": "turnovers",
    "fouls": "fouls",
}


def parse_scoreboard(payload: object) -> tuple[ScoreboardGame, ...]:
    """Parse a scoreboard response into normalized games."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"scoreboard payload must be an object, got {type(payload).__name__}"
        )
    events = require_sequence(payload, "events", PROVIDER, "scoreboard")
    return tuple(
        _parse_event(event, f"events[{i}]") for i, event in enumerate(events)
    )


def _parse_event(event: object, context: str) -> ScoreboardGame:
    if not isinstance(event, Mapping):
        raise ProviderValidationError(PROVIDER, "event must be an object", context=context)
    event_id = require_str(event, "id", PROVIDER, context)
    start_time = parse_datetime_utc(
        require(event, "date", PROVIDER, context), PROVIDER, f"{context}.date"
    )
    season = parse_int(
        require(require_mapping(event, "season", PROVIDER, context), "year", PROVIDER, context),
        PROVIDER,
        f"{context}.season.year",
    )
    status = _parse_status(event, context)

    competitions = require_sequence(event, "competitions", PROVIDER, context)
    if not competitions:
        raise ProviderValidationError(PROVIDER, "event has no competitions", context=context)
    competition = competitions[0]
    if not isinstance(competition, Mapping):
        raise ProviderValidationError(
            PROVIDER, "competition must be an object", context=context
        )
    competitors = require_sequence(
        competition, "competitors", PROVIDER, f"{context}.competitions[0]"
    )
    if len(competitors) != 2:
        raise ProviderValidationError(
            PROVIDER,
            f"expected exactly 2 competitors, got {len(competitors)}",
            context=f"{context}.competitions[0]",
        )

    sides: dict[str, tuple[TeamRef, int | None]] = {}
    for j, competitor in enumerate(competitors):
        comp_context = f"{context}.competitions[0].competitors[{j}]"
        if not isinstance(competitor, Mapping):
            raise ProviderValidationError(
                PROVIDER, "competitor must be an object", context=comp_context
            )
        home_away = require_str(competitor, "homeAway", PROVIDER, comp_context)
        team = _parse_team(competitor, comp_context)
        raw_score = competitor.get("score")
        score = (
            None
            if raw_score in (None, "")
            else parse_int(raw_score, PROVIDER, f"{comp_context}.score")
        )
        sides[home_away] = (team, score)

    if set(sides) != {"home", "away"}:
        raise ProviderValidationError(
            PROVIDER,
            f"expected one home and one away competitor, got {sorted(sides)}",
            context=context,
        )

    home_team, home_score = sides["home"]
    away_team, away_score = sides["away"]
    return ScoreboardGame(
        external_id=event_id,
        start_time=start_time,
        season=season,
        status=status,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
    )


def _parse_status(event: Mapping[str, object], context: str) -> GameStatus:
    status_type = require_mapping(
        require_mapping(event, "status", PROVIDER, context), "type", PROVIDER, f"{context}.status"
    )
    name = require_str(status_type, "name", PROVIDER, f"{context}.status.type")
    return _STATUS_MAP.get(name, GameStatus.OTHER)


def _parse_team(container: Mapping[str, object], context: str) -> TeamRef:
    team = require_mapping(container, "team", PROVIDER, context)
    return TeamRef(
        external_id=require_str(team, "id", PROVIDER, f"{context}.team"),
        name=require_str(team, "displayName", PROVIDER, f"{context}.team"),
        abbreviation=require_str(team, "abbreviation", PROVIDER, f"{context}.team"),
    )


def parse_summary(payload: object) -> GameBoxScore:
    """Parse a summary response into a full game box score."""
    if not isinstance(payload, Mapping):
        raise ProviderValidationError(
            PROVIDER, f"summary payload must be an object, got {type(payload).__name__}"
        )
    header = require_mapping(payload, "header", PROVIDER, "summary")
    game_id = require_str(header, "id", PROVIDER, "summary.header")
    boxscore = require_mapping(payload, "boxscore", PROVIDER, "summary")

    raw_teams = require_sequence(boxscore, "teams", PROVIDER, "summary.boxscore")
    teams = tuple(
        _parse_team_box(entry, f"boxscore.teams[{i}]") for i, entry in enumerate(raw_teams)
    )

    raw_players = require_sequence(boxscore, "players", PROVIDER, "summary.boxscore")
    players: list[PlayerBoxLine] = []
    for i, entry in enumerate(raw_players):
        players.extend(_parse_team_players(entry, f"boxscore.players[{i}]"))

    return GameBoxScore(game_external_id=game_id, teams=teams, players=tuple(players))


def _parse_team_box(entry: object, context: str) -> TeamBoxScore:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "team entry must be an object", context=context)
    team = _parse_team(entry, context)
    statistics = require_sequence(entry, "statistics", PROVIDER, context)
    by_name: dict[str, str] = {}
    for stat in statistics:
        if isinstance(stat, Mapping):
            name = stat.get("name")
            value = stat.get("displayValue")
            if isinstance(name, str) and isinstance(value, str):
                by_name[name] = value

    def stat_value(field: str) -> str:
        stat_name = _TEAM_STAT_NAMES[field]
        if stat_name not in by_name:
            raise ProviderValidationError(
                PROVIDER, f"missing team statistic '{stat_name}'", context=context
            )
        return by_name[stat_name]

    return TeamBoxScore(
        team=team,
        field_goals=_parse_shooting(stat_value("field_goals"), f"{context}.FG"),
        three_pointers=_parse_shooting(stat_value("three_pointers"), f"{context}.3PT"),
        free_throws=_parse_shooting(stat_value("free_throws"), f"{context}.FT"),
        rebounds=parse_int(stat_value("rebounds"), PROVIDER, f"{context}.REB"),
        offensive_rebounds=parse_int(stat_value("offensive_rebounds"), PROVIDER, context),
        defensive_rebounds=parse_int(stat_value("defensive_rebounds"), PROVIDER, context),
        assists=parse_int(stat_value("assists"), PROVIDER, f"{context}.AST"),
        steals=parse_int(stat_value("steals"), PROVIDER, f"{context}.STL"),
        blocks=parse_int(stat_value("blocks"), PROVIDER, f"{context}.BLK"),
        turnovers=parse_int(stat_value("turnovers"), PROVIDER, f"{context}.TO"),
        fouls=parse_int(stat_value("fouls"), PROVIDER, f"{context}.PF"),
    )


def _parse_team_players(entry: object, context: str) -> tuple[PlayerBoxLine, ...]:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "players entry must be an object", context=context)
    team = _parse_team(entry, context)
    statistics = require_sequence(entry, "statistics", PROVIDER, context)
    if not statistics:
        return ()
    block = statistics[0]
    if not isinstance(block, Mapping):
        raise ProviderValidationError(
            PROVIDER, "statistics[0] must be an object", context=context
        )
    labels = tuple(require_sequence(block, "labels", PROVIDER, f"{context}.statistics[0]"))
    if labels != EXPECTED_PLAYER_LABELS:
        raise ProviderValidationError(
            PROVIDER,
            f"unexpected stat labels {labels!r}; expected {EXPECTED_PLAYER_LABELS!r}",
            context=f"{context}.statistics[0].labels",
        )
    athletes = require_sequence(block, "athletes", PROVIDER, f"{context}.statistics[0]")
    return tuple(
        _parse_athlete(athlete, team, f"{context}.statistics[0].athletes[{j}]")
        for j, athlete in enumerate(athletes)
    )


def _parse_athlete(entry: object, team: TeamRef, context: str) -> PlayerBoxLine:
    if not isinstance(entry, Mapping):
        raise ProviderValidationError(PROVIDER, "athlete entry must be an object", context=context)
    athlete = require_mapping(entry, "athlete", PROVIDER, context)
    position = athlete.get("position")
    position_abbr = (
        position.get("abbreviation") if isinstance(position, Mapping) else None
    )
    player = PlayerRef(
        external_id=require_str(athlete, "id", PROVIDER, f"{context}.athlete"),
        full_name=require_str(athlete, "displayName", PROVIDER, f"{context}.athlete"),
        position=position_abbr if isinstance(position_abbr, str) else None,
    )
    starter = bool(entry.get("starter", False))
    did_not_play = bool(entry.get("didNotPlay", False))
    raw_stats = entry.get("stats")
    if did_not_play or not raw_stats:
        return _empty_line(player, team, starter=starter, did_not_play=did_not_play)

    if not isinstance(raw_stats, Sequence) or len(raw_stats) != len(EXPECTED_PLAYER_LABELS):
        raise ProviderValidationError(
            PROVIDER,
            f"stats array length {len(raw_stats)} does not match labels",
            context=context,
        )
    values = dict(zip(EXPECTED_PLAYER_LABELS, raw_stats, strict=True))
    return PlayerBoxLine(
        player=player,
        team=team,
        starter=starter,
        did_not_play=did_not_play,
        minutes=optional_int(values["MIN"], PROVIDER, f"{context}.MIN"),
        points=optional_int(values["PTS"], PROVIDER, f"{context}.PTS"),
        field_goals=_parse_shooting(values["FG"], f"{context}.FG"),
        three_pointers=_parse_shooting(values["3PT"], f"{context}.3PT"),
        free_throws=_parse_shooting(values["FT"], f"{context}.FT"),
        rebounds=optional_int(values["REB"], PROVIDER, f"{context}.REB"),
        offensive_rebounds=optional_int(values["OREB"], PROVIDER, f"{context}.OREB"),
        defensive_rebounds=optional_int(values["DREB"], PROVIDER, f"{context}.DREB"),
        assists=optional_int(values["AST"], PROVIDER, f"{context}.AST"),
        steals=optional_int(values["STL"], PROVIDER, f"{context}.STL"),
        blocks=optional_int(values["BLK"], PROVIDER, f"{context}.BLK"),
        turnovers=optional_int(values["TO"], PROVIDER, f"{context}.TO"),
        fouls=optional_int(values["PF"], PROVIDER, f"{context}.PF"),
        plus_minus=optional_int(values["+/-"], PROVIDER, f"{context}.+/-"),
    )


def _empty_line(
    player: PlayerRef, team: TeamRef, *, starter: bool, did_not_play: bool
) -> PlayerBoxLine:
    return PlayerBoxLine(
        player=player,
        team=team,
        starter=starter,
        did_not_play=did_not_play,
        minutes=None,
        points=None,
        field_goals=None,
        three_pointers=None,
        free_throws=None,
        rebounds=None,
        offensive_rebounds=None,
        defensive_rebounds=None,
        assists=None,
        steals=None,
        blocks=None,
        turnovers=None,
        fouls=None,
        plus_minus=None,
    )


def _parse_shooting(value: object, context: str) -> ShootingLine | None:
    if isinstance(value, str) and set(value.strip()) <= {"-"}:
        return None  # ESPN placeholder for an untracked line, e.g. '--'
    if not isinstance(value, str) or "-" not in value:
        raise ProviderValidationError(
            PROVIDER, f"expected 'made-attempted' string, got {value!r}", context=context
        )
    made_raw, _, attempted_raw = value.partition("-")
    return ShootingLine(
        made=parse_int(made_raw, PROVIDER, context),
        attempted=parse_int(attempted_raw, PROVIDER, context),
    )
