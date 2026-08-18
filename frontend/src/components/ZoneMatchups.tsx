/* Which rotation player on either side has a real zone edge tonight.
 *
 * Not "who is better" -- specifically, does a player's own season shooting
 * strength line up with the opponent they're about to face being genuinely
 * weak in that same zone. Both halves of that comparison are season-long,
 * never this pairing's own history: two teams meet a handful of times a
 * season, nowhere near enough shots to say anything about one matchup
 * specifically. See wnba_engine/analysis/zone_matchups.py for the exact bar
 * (both sides have to clear league average by 3+ points, independently) --
 * the same rule PlayerMatchup.tsx applies for one player on their own page,
 * run here for both rosters at once and ranked together.
 *
 * Frequently empty, on purpose: most nights, most rotation players are just
 * playing their own game against an average defense. An empty result here is
 * the honest answer, not a sign the feature is broken.
 */

import { Link } from "react-router-dom";
import { Async, PlayerCell } from "./ui";
import type { ZoneMatchupsResponse } from "../lib/api";
import { useQuery } from "../lib/api";
import { pct } from "../lib/format";
import { teamColor } from "../lib/teamColors";

export default function ZoneMatchups({
  gameId,
  homeTeamId,
  awayTeamId,
  homeAbbr,
  awayAbbr,
}: {
  gameId: number;
  homeTeamId: number;
  awayTeamId: number;
  homeAbbr: string;
  awayAbbr: string;
}) {
  const query = useQuery<ZoneMatchupsResponse>(`/games/${gameId}/zone-matchups`);
  const abbrOf = (teamId: number) => (teamId === homeTeamId ? homeAbbr : awayTeamId === teamId ? awayAbbr : "—");

  return (
    <Async
      query={query}
      empty={(data) => data.edges.length === 0}
      emptyMessage="No standout zone matchups tonight — checked, and neither rotation lines up against a real soft spot right now."
    >
      {(data) => (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th className="name">Player</th>
                  <th>Team</th>
                  <th>Zone</th>
                  <th>Shoots</th>
                  <th>Opp allows</th>
                  <th>League avg</th>
                </tr>
              </thead>
              <tbody>
                {data.edges.map((edge) => (
                  <tr key={`${edge.player_id}-${edge.zone}`}>
                    <td className="name">
                      <PlayerCell playerId={edge.player_id} name={edge.full_name} />
                    </td>
                    <td>
                      <span className="team-mark" style={{ fontSize: "var(--t-sm)", color: teamColor(abbrOf(edge.team_id)) }}>
                        {abbrOf(edge.team_id)}
                      </span>{" "}
                      <span className="muted">
                        vs{" "}
                        <Link to={`/teams/${edge.opponent_team_id}`}>{abbrOf(edge.opponent_team_id)}</Link>
                      </span>
                    </td>
                    <td>{edge.zone}</td>
                    <td className="num">{pct(edge.player_rate)}</td>
                    <td className="num">{pct(edge.defense_rate)}</td>
                    <td className="num muted">{pct(edge.league_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="prose" style={{ marginTop: "var(--s-3)" }}>
            Both sides season-long: this player's shooting from this zone, and this opponent's shooting
            allowed from it, each against the league average. Ranked by combined size of edge. Not a
            forecast -- a hot zone can go cold, and a defense can key on a scout report this doesn't see.
          </p>
        </>
      )}
    </Async>
  );
}
