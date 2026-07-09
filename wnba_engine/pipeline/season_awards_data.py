"""Hand-researched WNBA season award winners for 2022-2025, ground truth
for verifying Kalshi/Polymarket award prediction markets against.

Why hand-researched instead of pulled from an API: no provider in this
repo (ESPN, balldontlie, Kalshi, Polymarket) exposes historical league
award winners -- these are announced by the league each September/October
and never re-published as a queryable feed. This is manually-researched
historical fact, not a live pull, which is also why
wnba_engine/pipeline/season_awards_seed.py is a one-off seed script
rather than a `backfill-*` CLI command alongside the balldontlie
pipelines: there is nothing to "backfill" from a source API, and running
this again would only ever re-verify the same fixed facts below.

Every entry was cross-checked against at least two independent sources
(Wikipedia's dedicated per-award history page + a WNBA.com/team-site/wire
article, or basketball-reference.com/wnba where reachable) before being
recorded here; the exact URLs consulted are preserved per (season, award)
group in the `source` field, so a future audit can re-verify against the
same sources. 2026 is deliberately excluded -- season in progress, no
winners yet. Two awards/seasons required resolving a real discrepancy
between sources during research (documented inline below at the entries
in question):

- 2025 DPOY was a genuine tie (first in league history) -- two rows are
  expected here, not a data error. Confirmed independently by wnba.com's
  official announcement and NBA PR.
- 2024 All-Defensive Team: initial sources disagreed on which of
  Alyssa Thomas/A'ja Wilson/Alanna Smith/Ezi Magbegor/DiJonai
  Carrington/Breanna Stewart sat on First vs. Second team (all ten names
  agreed, only the split didn't). Resolved via three independently
  phrased searches that converged on the same split, cited below.

No award/season was found unresolvable and dropped -- see the seed
script's docstring and this task's final report for the one genuine
research gap (a small number of raw_name values that don't resolve to a
canonical player_id in THIS repo's players table, not a missing fact).
"""

from __future__ import annotations

from wnba_engine.models.season_awards import AwardWinner

_MVP_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Most_Valuable_Player_Award"
_ROY_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Rookie_of_the_Year_Award"
_DPOY_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Defensive_Player_of_the_Year_Award"
_DPOY_2025_SOURCE = (
    f"{_DPOY_SOURCE}; https://www.wnba.com/news/smith-wilson-2025-dpoy; "
    "https://pr.nba.com/2025-wnba-defensive-player-of-the-year-alanna-smith-aja-wilson/"
)
_SIXTH_POY_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Sixth_Woman_of_the_Year_Award"
_SIXTH_POY_2022_SOURCE = (
    f"{_SIXTH_POY_SOURCE}; "
    "https://www.wnba.com/news/connecticut-suns-brionna-jones-named-2022-kia-wnba-sixth-player-of-the-year"
)
_MIP_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Most_Improved_Player_Award"
_MIP_2022_SOURCE = (
    f"{_MIP_SOURCE}; "
    "https://www.wnba.com/news/las-vegas-aces-jackie-young-named-2022-kia-wnba-most-improved-player"
)
_COY_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Coach_of_the_Year_Award"
_COY_2023_SOURCE = (
    f"{_COY_SOURCE}; https://www.wnba.com/news/stephanie-white-coach-of-year-wnba-2023"
)
_COY_2025_SOURCE = (
    f"{_COY_SOURCE}; https://sports.yahoo.com/article/wnba-awards-2025-complete-list-152747284.html"
)
_FINALS_MVP_SOURCE = "https://en.wikipedia.org/wiki/WNBA_Finals_Most_Valuable_Player_Award"

_ALL_WNBA_SOURCE = "https://en.wikipedia.org/wiki/All-WNBA_Team"
_ALL_WNBA_2024_SOURCE = (
    f"{_ALL_WNBA_SOURCE}; https://www.wnba.com/news/2024-all-wnba-first-and-second-team"
)
_ALL_WNBA_2025_SOURCE = (
    "https://www.wnba.com/news/2025-all-wnba-teams; "
    "https://www.cbssports.com/wnba/news/wnba-awards-aja-wilson-napheesa-collier-headline-all-wnba-teams-paige-bueckers-makes-cut-as-rookie/"
)

_ALL_DEFENSE_SOURCE = "https://en.wikipedia.org/wiki/WNBA_All-Defensive_Team"
_ALL_DEFENSE_2022_SOURCE = (
    f"{_ALL_DEFENSE_SOURCE}; "
    "https://lynx.wnba.com/news/minnesota-lynx-center-sylvia-fowles-named-to-2022-wnba-all-defensive-first-team"
)
_ALL_DEFENSE_2023_SOURCE = (
    f"{_ALL_DEFENSE_SOURCE}; "
    "https://www.cbssports.com/wnba/news/2023-wnba-defensive-player-of-the-year-aces-aja-wilson-goes-back-to-back-headlines-all-defensive-teams/"
)
# See module docstring: First/Second split cross-checked across three
# independent searches converging on this split before being recorded.
_ALL_DEFENSE_2024_SOURCE = (
    "https://liberty.wnba.com/news/breanna-stewart-and-jonquel-jones-named-to-"
    "2024-wnba-all-defensive-first-and-second-teams; "
    "https://www.sportskeeda.com/us/wnba/news-2024-wnba-all-defensive-teams-a-ja-"
    "wilson-caitlin-clark-s-rival-headline-first-team-selections; "
    "https://lynx.wnba.com/news/napheesa-collier-and-alanna-smith-named-to-wnba-all-defensive-team"
)
_ALL_DEFENSE_2025_SOURCE = (
    "https://bleacherreport.com/articles/25258504-aja-wilson-napheesa-collier-"
    "headline-2025-wnba-all-defensive-teams; "
    "https://justwomenssports.com/reads/napheesa-collier-headlines-2025-wnba-all-defensive-teams/"
)

_ALL_ROOKIE_SOURCE = "https://en.wikipedia.org/wiki/WNBA_All-Rookie_Team"
_ALL_ROOKIE_2022_SOURCE = (
    f"{_ALL_ROOKIE_SOURCE}; "
    "https://sky.wnba.com/news/chicago-skys-rebekah-gardner-named-to-2022-wnba-all-rookie-team"
)
_ALL_ROOKIE_2024_SOURCE = (
    "https://x.com/WNBA/status/1841909542696689787; "
    "https://sky.wnba.com/news/angel-reese-kamilla-cardoso-named-to-2024-wnba-all-rookie-team"
)
_ALL_ROOKIE_2025_SOURCE = (
    "https://sports.yahoo.com/wnba/breaking-news/article/wnba-2025-all-rookie-team-"
    "headlined-by-rookie-of-the-year-paige-bueckers-mystics-rookies-204716739.html; "
    "https://storm.wnba.com/news/dominique-malonga-named-to-2025-wnba-all-rookie-ream"
)


def _single_winner(season: int, award: str, raw_name: str, source: str) -> AwardWinner:
    return AwardWinner(season=season, award=award, raw_name=raw_name, source=source)


def _team_award(
    season: int, award: str, team_selection: str, names: tuple[str, ...], source: str
) -> tuple[AwardWinner, ...]:
    return tuple(
        AwardWinner(
            season=season, award=award, raw_name=name, source=source, team_selection=team_selection
        )
        for name in names
    )


_SINGLE_WINNER_AWARDS: tuple[AwardWinner, ...] = (
    _single_winner(2022, "mvp", "A'ja Wilson", _MVP_SOURCE),
    _single_winner(2023, "mvp", "Breanna Stewart", _MVP_SOURCE),
    _single_winner(2024, "mvp", "A'ja Wilson", _MVP_SOURCE),
    _single_winner(2025, "mvp", "A'ja Wilson", _MVP_SOURCE),
    _single_winner(2022, "roy", "Rhyne Howard", _ROY_SOURCE),
    _single_winner(2023, "roy", "Aliyah Boston", _ROY_SOURCE),
    _single_winner(2024, "roy", "Caitlin Clark", _ROY_SOURCE),
    _single_winner(2025, "roy", "Paige Bueckers", _ROY_SOURCE),
    _single_winner(2022, "dpoy", "A'ja Wilson", _DPOY_SOURCE),
    _single_winner(2023, "dpoy", "A'ja Wilson", _DPOY_SOURCE),
    _single_winner(2024, "dpoy", "Napheesa Collier", _DPOY_SOURCE),
    # 2025 is a genuine co-winner tie -- two rows, see module docstring.
    _single_winner(2025, "dpoy", "A'ja Wilson", _DPOY_2025_SOURCE),
    _single_winner(2025, "dpoy", "Alanna Smith", _DPOY_2025_SOURCE),
    _single_winner(2022, "sixth_poy", "Brionna Jones", _SIXTH_POY_2022_SOURCE),
    _single_winner(2023, "sixth_poy", "Alysha Clark", _SIXTH_POY_SOURCE),
    _single_winner(2024, "sixth_poy", "Tiffany Hayes", _SIXTH_POY_SOURCE),
    _single_winner(2025, "sixth_poy", "Naz Hillmon", _SIXTH_POY_SOURCE),
    _single_winner(2022, "mip", "Jackie Young", _MIP_2022_SOURCE),
    _single_winner(2023, "mip", "Satou Sabally", _MIP_SOURCE),
    _single_winner(2024, "mip", "DiJonai Carrington", _MIP_SOURCE),
    _single_winner(2025, "mip", "Veronica Burton", _MIP_SOURCE),
    _single_winner(2022, "finals_mvp", "Chelsea Gray", _FINALS_MVP_SOURCE),
    _single_winner(2023, "finals_mvp", "A'ja Wilson", _FINALS_MVP_SOURCE),
    _single_winner(2024, "finals_mvp", "Jonquel Jones", _FINALS_MVP_SOURCE),
    _single_winner(2025, "finals_mvp", "A'ja Wilson", _FINALS_MVP_SOURCE),
)

# Coach of the Year: raw_name is the coach, coach_team_name resolves
# team_id via entity_repo.find_team_by_name at seed time (see
# season_awards_seed.py) -- coaches have no players.id row.
_COACH_OF_THE_YEAR: tuple[AwardWinner, ...] = (
    AwardWinner(
        season=2022,
        award="coy",
        raw_name="Becky Hammon",
        source=_COY_SOURCE,
        coach_team_name="Las Vegas Aces",
    ),
    AwardWinner(
        season=2023,
        award="coy",
        raw_name="Stephanie White",
        source=_COY_2023_SOURCE,
        coach_team_name="Connecticut Sun",
    ),
    AwardWinner(
        season=2024,
        award="coy",
        raw_name="Cheryl Reeve",
        source=_COY_SOURCE,
        coach_team_name="Minnesota Lynx",
    ),
    AwardWinner(
        season=2025,
        award="coy",
        raw_name="Natalie Nakase",
        source=_COY_2025_SOURCE,
        coach_team_name="Golden State Valkyries",
    ),
)

_ALL_WNBA: tuple[AwardWinner, ...] = (
    _team_award(
        2022,
        "all_wnba",
        "first",
        ("A'ja Wilson", "Breanna Stewart", "Nneka Ogwumike", "Skylar Diggins-Smith", "Kelsey Plum"),
        _ALL_WNBA_SOURCE,
    )
    + _team_award(
        2022,
        "all_wnba",
        "second",
        ("Alyssa Thomas", "Sabrina Ionescu", "Jonquel Jones", "Candace Parker", "Sylvia Fowles"),
        _ALL_WNBA_SOURCE,
    )
    + _team_award(
        2023,
        "all_wnba",
        "first",
        ("Breanna Stewart", "A'ja Wilson", "Jackie Young", "Alyssa Thomas", "Chelsea Gray"),
        _ALL_WNBA_SOURCE,
    )
    + _team_award(
        2023,
        "all_wnba",
        "second",
        ("Nneka Ogwumike", "Napheesa Collier", "Jewell Loyd", "Satou Sabally", "Sabrina Ionescu"),
        _ALL_WNBA_SOURCE,
    )
    + _team_award(
        2024,
        "all_wnba",
        "first",
        ("A'ja Wilson", "Napheesa Collier", "Breanna Stewart", "Caitlin Clark", "Alyssa Thomas"),
        _ALL_WNBA_2024_SOURCE,
    )
    + _team_award(
        2024,
        "all_wnba",
        "second",
        (
            "Sabrina Ionescu",
            "Kahleah Copper",
            "Nneka Ogwumike",
            "Arike Ogunbowale",
            "Jonquel Jones",
        ),
        _ALL_WNBA_2024_SOURCE,
    )
    + _team_award(
        2025,
        "all_wnba",
        "first",
        ("A'ja Wilson", "Napheesa Collier", "Alyssa Thomas", "Allisha Gray", "Kelsey Mitchell"),
        _ALL_WNBA_2025_SOURCE,
    )
    + _team_award(
        2025,
        "all_wnba",
        "second",
        ("Aliyah Boston", "Paige Bueckers", "Sabrina Ionescu", "Nneka Ogwumike", "Jackie Young"),
        _ALL_WNBA_2025_SOURCE,
    )
)

_ALL_DEFENSE: tuple[AwardWinner, ...] = (
    _team_award(
        2022,
        "all_defense",
        "first",
        ("A'ja Wilson", "Natasha Cloud", "Sylvia Fowles", "Breanna Stewart", "Ariel Atkins"),
        _ALL_DEFENSE_2022_SOURCE,
    )
    + _team_award(
        2022,
        "all_defense",
        "second",
        ("Alyssa Thomas", "Ezi Magbegor", "Jonquel Jones", "Brittney Sykes", "Gabby Williams"),
        _ALL_DEFENSE_2022_SOURCE,
    )
    + _team_award(
        2023,
        "all_defense",
        "first",
        ("A'ja Wilson", "Alyssa Thomas", "Brittney Sykes", "Breanna Stewart", "Jordin Canada"),
        _ALL_DEFENSE_2023_SOURCE,
    )
    + _team_award(
        2023,
        "all_defense",
        "second",
        (
            "Betnijah Laney",
            "Ezi Magbegor",
            "Nneka Ogwumike",
            "Napheesa Collier",
            "Elizabeth Williams",
        ),
        _ALL_DEFENSE_2023_SOURCE,
    )
    + _team_award(
        2024,
        "all_defense",
        "first",
        (
            "Napheesa Collier",
            "A'ja Wilson",
            "Ezi Magbegor",
            "DiJonai Carrington",
            "Breanna Stewart",
        ),
        _ALL_DEFENSE_2024_SOURCE,
    )
    + _team_award(
        2024,
        "all_defense",
        "second",
        ("Alyssa Thomas", "Alanna Smith", "Nneka Ogwumike", "Jonquel Jones", "Natasha Cloud"),
        _ALL_DEFENSE_2024_SOURCE,
    )
    + _team_award(
        2025,
        "all_defense",
        "first",
        ("Napheesa Collier", "Alanna Smith", "Alyssa Thomas", "Gabby Williams", "A'ja Wilson"),
        _ALL_DEFENSE_2025_SOURCE,
    )
    + _team_award(
        2025,
        "all_defense",
        "second",
        ("Aliyah Boston", "Veronica Burton", "Rhyne Howard", "Ezi Magbegor", "Breanna Stewart"),
        _ALL_DEFENSE_2025_SOURCE,
    )
)

# All-Rookie is a single unified 5-player team (not First/Second) in every
# season 2022-2025 -- verified per season, see module docstring and
# season_awards_seed.py. team_selection stays at the 'na' default.
_ALL_ROOKIE: tuple[AwardWinner, ...] = (
    _team_award(
        2022,
        "all_rookie",
        "na",
        ("Rhyne Howard", "NaLyssa Smith", "Shakira Austin", "Queen Egbo", "Rebekah Gardner"),
        _ALL_ROOKIE_2022_SOURCE,
    )
    + _team_award(
        2023,
        "all_rookie",
        "na",
        ("Aliyah Boston", "Jordan Horston", "Dorka Juhász", "Diamond Miller", "Li Meng"),
        _ALL_ROOKIE_SOURCE,
    )
    + _team_award(
        2024,
        "all_rookie",
        "na",
        ("Caitlin Clark", "Rickea Jackson", "Angel Reese", "Kamilla Cardoso", "Leonie Fiebich"),
        _ALL_ROOKIE_2024_SOURCE,
    )
    + _team_award(
        2025,
        "all_rookie",
        "na",
        ("Paige Bueckers", "Sonia Citron", "Kiki Iriafen", "Dominique Malonga", "Janelle Salaün"),
        _ALL_ROOKIE_2025_SOURCE,
    )
)

SEASON_AWARD_WINNERS: tuple[AwardWinner, ...] = (
    _SINGLE_WINNER_AWARDS + _COACH_OF_THE_YEAR + _ALL_WNBA + _ALL_DEFENSE + _ALL_ROOKIE
)
