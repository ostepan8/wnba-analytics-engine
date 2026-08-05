"""Individually-verified, known-benign check violations.

Some checks surface real, permanent disagreements that are NOT bugs --
usually because an upstream provider is internally inconsistent in a way
we can observe but not fix (see the entries below). Left unhandled, those
violations make `wnba-engine validate` exit non-zero forever, which
destroys its value as a gate: if the command is always red, nobody
notices when it goes red for a NEW reason.

The fix is deliberately NOT a blanket per-check suppression. Each entry
here acknowledges ONE specific violation, identified by a key that
encodes the actual values involved, alongside the evidence that cleared
it. Consequences of that design, all intentional:

- A genuinely new violation of an acknowledged check still FAILS. Only
  the exact listed one is muted.
- If an acknowledged violation CHANGES (a score shifts, a third external
  id joins a mapping), its key no longer matches and it fails again --
  re-verification is forced rather than assumed.
- If an acknowledged violation is fixed upstream and disappears,
  `check_stale_acknowledgements` reports the dead entry so this file
  doesn't rot into a list of things that stopped being true.

This preserves the property the original crosswalk-check docstring
argued for -- never silently hide a legitimate-looking pattern, because
it might be a genuinely bad future merge -- while still letting the
suite go green on a database whose only violations are understood.
"""

from __future__ import annotations

from dataclasses import dataclass

CHECK_DUPLICATE_CROSSWALK = "duplicate_crosswalk_mappings"
CHECK_PLAYS_FINAL_SCORE = "plays_final_score_matches_game_score"
CHECK_GAME_COUNTS = "regular_season_game_counts"
CHECK_PLAY_POINTS = "play_points_match_final_score"


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """One verified-benign violation.

    `key` must match the key the owning check derives for that violation
    row (see each check's `key_fn`), and encodes the specific values --
    not just the row's identity -- so any change re-raises the failure.
    """

    check_name: str
    key: str
    reason: str
    verified_on: str


ACKNOWLEDGEMENTS: tuple[Acknowledgement, ...] = (
    # balldontlie issues a different player id for the same real person
    # across its own separate endpoints (advanced-stats vs traditional
    # box-score). Each was verified by confirming both external_ids
    # appear under the SAME team_id in player_advanced_stats /
    # player_game_stats -- strong evidence of one person, not a bad
    # name-match merge. Re-verify that way if a new one appears.
    Acknowledgement(
        check_name=CHECK_DUPLICATE_CROSSWALK,
        key="balldontlie/player/284:67134,80698",
        reason="balldontlie's own duplicate player id across endpoints; same team_id both times",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_DUPLICATE_CROSSWALK,
        key="balldontlie/player/300:74872,80580",
        reason="balldontlie's own duplicate player id across endpoints; same team_id both times",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_DUPLICATE_CROSSWALK,
        key="balldontlie/player/554:101929,75090",
        reason="balldontlie's own duplicate player id across endpoints; same team_id both times",
        verified_on="2026-07-29",
    ),
    # the-odds-api re-issued the event id for one real game mid-life.
    # Game 226 (2022-07-14, Liberty vs Aces) was quoted under
    # 90172a3f... through 2022-07-13 02:20, then under c28ae79b... from
    # 2022-07-13 23:47. Verified benign by the line handing over
    # unbroken across the switch: fanduel's last 90172a3f quote and its
    # first c28ae79b quote are identical (ml 235/-303, spread 6.5,
    # total 172.5). The separate 2022-07-12 meeting of the same two
    # teams (game 221) has its own distinct event id, b36b5bcb..., so
    # this is not the team+date matcher collapsing two games.
    Acknowledgement(
        check_name=CHECK_DUPLICATE_CROSSWALK,
        key=(
            "the_odds_api/game/226:"
            "90172a3f4bb05d9927f27a0879f8fc16,c28ae79b1b4ac51afaca4d1d7241d8c2"
        ),
        reason="the-odds-api re-issued the event id mid-game; line continuous across the switch",
        verified_on="2026-07-29",
    ),
    # balldontlie's play-by-play and ESPN's scoreboard disagree by 1-2
    # points on 6 of ~1,240 games (0.48%). Two fully independent
    # providers, no shared upstream -- real vendor noise, not an
    # ingestion bug. ESPN remains the source of record for
    # games.home_score/away_score; nothing is written back from plays.
    Acknowledgement(
        check_name=CHECK_PLAYS_FINAL_SCORE,
        key="866:81-59:81-58",
        reason="balldontlie play-by-play vs ESPN scoreboard, 1pt upstream disagreement",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_PLAYS_FINAL_SCORE,
        key="950:81-84:80-84",
        reason="balldontlie play-by-play vs ESPN scoreboard, 1pt upstream disagreement",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_PLAYS_FINAL_SCORE,
        key="1004:103-86:101-86",
        reason="balldontlie play-by-play vs ESPN scoreboard, 2pt upstream disagreement",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_PLAYS_FINAL_SCORE,
        key="1129:84-76:83-76",
        reason="balldontlie play-by-play vs ESPN scoreboard, 1pt upstream disagreement",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_PLAYS_FINAL_SCORE,
        key="1156:83-98:81-98",
        reason="balldontlie play-by-play vs ESPN scoreboard, 2pt upstream disagreement",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_PLAYS_FINAL_SCORE,
        key="1218:69-79:67-79",
        reason="balldontlie play-by-play vs ESPN scoreboard, 2pt upstream disagreement",
        verified_on="2026-07-29",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2022/Chicago Sky:37",
        reason=(
            "the 2022 Commissioner's Cup final (2022-07-26, Las Vegas 93, Chicago 83) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2022/Las Vegas Aces:37",
        reason=(
            "the 2022 Commissioner's Cup final (2022-07-26, Las Vegas 93, Chicago 83) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2023/Las Vegas Aces:41",
        reason=(
            "the 2023 Commissioner's Cup final (2023-08-15, New York 82, Las Vegas 63) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2023/New York Liberty:41",
        reason=(
            "the 2023 Commissioner's Cup final (2023-08-15, New York 82, Las Vegas 63) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2024/Minnesota Lynx:41",
        reason=(
            "the 2024 Commissioner's Cup final (2024-06-25, Minnesota 94, New York 89) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2024/New York Liberty:41",
        reason=(
            "the 2024 Commissioner's Cup final (2024-06-25, Minnesota 94, New York 89) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2025/Indiana Fever:45",
        reason=(
            "the 2025 Commissioner's Cup final (2025-07-01, Indiana 74, Minnesota 59) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_GAME_COUNTS,
        key="2025/Minnesota Lynx:45",
        reason=(
            "the 2025 Commissioner's Cup final (2025-07-01, Indiana 74, Minnesota 59) is reported "
            "by ESPN with season_type='regular-season' but does not count "
            "toward regular-season standings, so both finalists show one "
            "extra game. The game was really played and its box score is "
            "real, so it is kept rather than dropped."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_PLAY_POINTS,
        key="131/balldontlie:136",
        reason=(
            "balldontlie's play feed for this 2022 game is incomplete: its "
            "scoring plays sum to 136 against a final score of 135. The box "
            "score and final score are right, only the play stream is short. "
            "stats.wnba.com reconciles exactly on every game it covers, so this "
            "is an upstream gap in one provider rather than a game we have wrong "
            "-- 4 of 1,300 balldontlie games, 0.3%."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_PLAY_POINTS,
        key="1367/balldontlie:174",
        reason=(
            "balldontlie's play feed for this 2026 game is incomplete: its "
            "scoring plays sum to 174 against a final score of 207. The box "
            "score and final score are right, only the play stream is short. "
            "stats.wnba.com reconciles exactly on every game it covers, so this "
            "is an upstream gap in one provider rather than a game we have wrong "
            "-- 4 of 1,300 balldontlie games, 0.3%."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_PLAY_POINTS,
        key="577/balldontlie:173",
        reason=(
            "balldontlie's play feed for this 2023 game is incomplete: its "
            "scoring plays sum to 173 against a final score of 175. The box "
            "score and final score are right, only the play stream is short. "
            "stats.wnba.com reconciles exactly on every game it covers, so this "
            "is an upstream gap in one provider rather than a game we have wrong "
            "-- 4 of 1,300 balldontlie games, 0.3%."
        ),
        verified_on="2026-08-04",
    ),
    Acknowledgement(
        check_name=CHECK_PLAY_POINTS,
        key="694/balldontlie:181",
        reason=(
            "balldontlie's play feed for this 2024 game is incomplete: its "
            "scoring plays sum to 181 against a final score of 173. The box "
            "score and final score are right, only the play stream is short. "
            "stats.wnba.com reconciles exactly on every game it covers, so this "
            "is an upstream gap in one provider rather than a game we have wrong "
            "-- 4 of 1,300 balldontlie games, 0.3%."
        ),
        verified_on="2026-08-04",
    ),
)


def acknowledged_keys(check_name: str) -> frozenset[str]:
    """Keys acknowledged for one check. Empty for any unlisted check, so
    a check with no entries here behaves exactly as it did before.
    """
    return frozenset(a.key for a in ACKNOWLEDGEMENTS if a.check_name == check_name)


def lookup(check_name: str, key: str) -> Acknowledgement | None:
    """The acknowledgement covering one violation, if any -- used to show
    the reason alongside a muted violation instead of hiding it outright.
    """
    for entry in ACKNOWLEDGEMENTS:
        if entry.check_name == check_name and entry.key == key:
            return entry
    return None
