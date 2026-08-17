/* What today actually holds, above the games rather than inside them.
 *
 * A scoreboard that opens on five collapsed cards asks the reader to guess
 * whether there is anything in it. These are the counts that answer that
 * without a click: how many games, how many props are priced, how many players
 * are out, and where the day's totals sit.
 */

import { Stat } from "./ui";
import type { SlateResponse } from "../lib/api";

export default function SlateBar({ slate }: { slate: SlateResponse }) {
  const { totals, games } = slate;

  /* Rest is invisible on a scoreboard and moves scoring more than most things
     that are visible on one, so the count of well-rested sides is worth a slot. */
  const restedTeams = Object.values(slate.teams).filter(
    (team) => (team.rest_days ?? 0) >= 3,
  ).length;

  return (
    <div
      className="grid grid--4"
      style={{ padding: "var(--s-3) var(--s-4)", borderBottom: "1px solid var(--line)" }}
    >
      <Stat
        value={totals.games}
        label="Games"
        detail={games.length === 1 ? undefined : `${Object.keys(slate.teams).length} teams`}
      />
      <Stat
        value={totals.props_priced}
        label="Props priced"
        detail={totals.props_priced === 0 ? "no live markets" : "Kalshi & Polymarket"}
      />
      <Stat
        value={totals.players_out}
        label="Players out"
        detail="out or doubtful"
      />
      <Stat
        value={totals.average_total ?? "—"}
        label="Average total"
        detail={
          totals.lines_recorded
            ? `${totals.lines_recorded} of ${totals.games} with a line`
            : "no lines recorded"
        }
      />
      {restedTeams > 0 && (
        <Stat value={restedTeams} label="Teams on 3+ days rest" />
      )}
    </div>
  );
}
