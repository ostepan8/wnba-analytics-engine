/* Shot location blocks shared between the collapsed scoreboard card
 * (GamePanel, on Home) and the standalone game page (GameDetail).
 *
 * Extracted rather than duplicated: GameDetail originally had no shot
 * sections at all even though the identical markup already existed inside
 * GamePanel for the same game, which meant the two views of one game
 * disagreed on what was worth showing.
 */

import { useState } from "react";
import GameShotPlot from "../charts/GameShotPlot";
import ShotChart from "../charts/ShotChart";
import { Async } from "./ui";
import type { GameShotsResponse, ShotDefenseResponse, TeamRecentShotsResponse } from "../lib/api";
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

const RECENT_WINDOWS = [5, 10, 20];

/** A team's shot chart from their recent games, not this one -- the preview
 *  for a game that has not been played yet, where "this game's shots" is
 *  necessarily empty. Binned, like a season chart, rather than plotted as
 *  individual attempts: 5-20 games is hundreds of shots, plenty to bin. */
function RecentTeamShots({ teamId, label }: { teamId: number; label: string }) {
  const [games, setGames] = useState(5);
  const query = useQuery<TeamRecentShotsResponse>(
    `/teams/${teamId}/shots/recent?last_n_games=${games}&bin_size=25`,
  );
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "var(--s-2)",
          marginBottom: "var(--s-2)",
        }}
      >
        <h4 style={{ fontSize: "var(--t-sm)", fontWeight: 620 }}>{label}</h4>
        <div style={{ display: "flex", gap: "var(--s-1)" }}>
          {RECENT_WINDOWS.map((n) => (
            <button
              key={n}
              className="control"
              aria-pressed={games === n}
              onClick={() => setGames(n)}
              style={{ height: 24, padding: "0 var(--s-2)", fontSize: "var(--t-xs)" }}
            >
              L{n}
            </button>
          ))}
        </div>
      </div>
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
              Last {data.games_found} game{data.games_found === 1 ? "" : "s"}
              {data.games_found < data.games_requested ? " (fewer played so far this season)" : ""} ·{" "}
              {num(data.attempts)} attempts · {data.points_per_attempt?.toFixed(2) ?? "—"} points per
              attempt. Recent form, not a preview of this specific matchup.
            </p>
          </>
        )}
      </Async>
    </div>
  );
}

/** Where one team actually shot from, this game. Individual attempts rather
 *  than a heat grid: a single game is too few shots for binning to read as
 *  anything but noise.
 *
 * A game that has not been played yet necessarily has none -- shown as a gap
 * in coverage, it reads as the site being broken rather than the game being
 * in the future. `gameStatus` tells the two cases apart. */
export function TeamShots({
  gameId,
  teamId,
  label,
  gameStatus,
}: {
  gameId: number;
  teamId: number;
  label: string;
  gameStatus: string;
}) {
  const upcoming = gameStatus !== "final";
  const query = useQuery<GameShotsResponse>(upcoming ? null : `/games/${gameId}/shots?team_id=${teamId}`);

  if (upcoming) {
    return <RecentTeamShots teamId={teamId} label={label} />;
  }

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
