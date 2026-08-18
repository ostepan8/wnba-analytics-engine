/* Shot location blocks shared between the collapsed scoreboard card
 * (GamePanel, on Home) and the standalone game page (GameDetail).
 *
 * Extracted rather than duplicated: GameDetail originally had no shot
 * sections at all even though the identical markup already existed inside
 * GamePanel for the same game, which meant the two views of one game
 * disagreed on what was worth showing.
 */

import GameShotPlot from "../charts/GameShotPlot";
import ShotChart from "../charts/ShotChart";
import { Async } from "./ui";
import type { GameShotsResponse, ShotDefenseResponse } from "../lib/api";
import { useQuery } from "../lib/api";
import { num } from "../lib/format";

function NotCovered({ what, why }: { what: string; why: string }) {
  return (
    <p className="empty">
      No {what} recorded for this game.
      <br />
      <span style={{ fontSize: "var(--t-xs)" }}>{why}</span>
    </p>
  );
}

/** Where one team actually shot from, this game. Individual attempts rather
 *  than a heat grid: a single game is too few shots for binning to read as
 *  anything but noise. */
export function TeamShots({
  gameId,
  teamId,
  label,
}: {
  gameId: number;
  teamId: number;
  label: string;
}) {
  const query = useQuery<GameShotsResponse>(`/games/${gameId}/shots?team_id=${teamId}`);
  if (!query.loading && !query.error && !query.data?.cells.length) {
    return (
      <div>
        <h4 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
          {label}
        </h4>
        <NotCovered
          what="shot locations"
          why="stats.wnba.com does not publish coordinates for every game; 261 of 281 games this season are covered."
        />
      </div>
    );
  }
  return (
    <div>
      <h4 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
        {label}
      </h4>
      <Async query={query} empty={(data) => (data.shots ?? []).length === 0}>
        {(data) => (
          <>
            <GameShotPlot shots={data.shots ?? []} />
            <p className="prose" style={{ marginTop: "var(--s-2)" }}>
              {data.points_per_attempt?.toFixed(2) ?? "—"} points per attempt
            </p>
          </>
        )}
      </Async>
    </div>
  );
}

/** How a team's whole season looks on defense, not just this game — one
 *  game is far too few shots to say where a defence leaks. */
export function TeamShotDefense({
  teamId,
  label,
  season,
}: {
  teamId: number;
  label: string;
  season: number;
}) {
  const query = useQuery<ShotDefenseResponse>(
    `/teams/${teamId}/defense?season=${season}&bin_size=25`,
  );
  return (
    <div>
      <h4 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
        {label} — shots allowed
      </h4>
      <Async query={query} empty={(data) => data.cells.length === 0}>
        {(data) => (
          <>
            <ShotChart
              cells={data.cells}
              binSize={data.bin_size}
              midpoint={data.points_per_attempt ?? 1}
              minAttempts={2}
            />
            <p className="prose" style={{ marginTop: "var(--s-2)" }}>
              {num(data.attempts)} allowed · {data.points_per_attempt?.toFixed(2) ?? "—"} pts/att.
              Blue is where opponents score <em>well</em> against this team — the defensive weak
              spots, not its strengths.
            </p>
          </>
        )}
      </Async>
    </div>
  );
}
