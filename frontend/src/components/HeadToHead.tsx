/* Previous meetings between the two sides.
 *
 * Scoped to games ALREADY PLAYED before the one being previewed, so a completed
 * game's own result never appears in its own matchup history.
 */

import { Link } from "react-router-dom";
import { Async } from "./ui";
import type { HeadToHeadResponse } from "../lib/api";
import { useQuery } from "../lib/api";
import { shortDateWithYear } from "../lib/format";

export default function HeadToHead({
  homeTeamId,
  awayTeamId,
  homeAbbr,
  awayAbbr,
  before,
}: {
  homeTeamId: number;
  awayTeamId: number;
  homeAbbr: string;
  awayAbbr: string;
  /** The previewed game's tip-off. Without it that game lists itself as its
      own prior history. */
  before: string;
}) {
  const query = useQuery<HeadToHeadResponse>(
    `/teams/${homeTeamId}/head-to-head/${awayTeamId}?limit=10&before=${encodeURIComponent(before)}`,
  );

  return (
    <Async query={query} empty={(data) => data.meetings.length === 0}>
      {(data) => (
        <>
          <p className="prose" style={{ marginBottom: "var(--s-3)" }}>
            <strong>
              {homeAbbr} {data.wins_a}–{data.wins_b} {awayAbbr}
            </strong>{" "}
            over {data.played} meeting{data.played === 1 ? "" : "s"}.
          </p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th className="name">Date</th>
                  <th>Matchup</th>
                  <th>Score</th>
                  <th>Winner</th>
                </tr>
              </thead>
              <tbody>
                {data.meetings.map((game) => {
                  const homeWon = (game.home_score ?? 0) > (game.away_score ?? 0);
                  return (
                    <tr key={game.id}>
                      <td className="name">
                        <Link to={`/games/${game.id}`}>{shortDateWithYear(game.start_time)}</Link>
                      </td>
                      <td>
                        {game.away_abbr} @ {game.home_abbr}
                      </td>
                      <td className="num">
                        {game.away_score}–{game.home_score}
                      </td>
                      <td>
                        <span className="badge badge--good">
                          {homeWon ? game.home_abbr : game.away_abbr}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Async>
  );
}
