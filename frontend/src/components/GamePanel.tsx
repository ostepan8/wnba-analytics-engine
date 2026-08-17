/* One game, expandable into everything known about it.
 *
 * Collapsed by default and lazy: a day can hold five games, and eagerly loading
 * lines, props, shots, defence and a box score for each would be thirty
 * requests to render a scoreboard. Each tab fetches only when it is opened, and
 * only for the game that was opened.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import GameFlow from "../charts/GameFlow";
import ShotChart, { ShotChartLegend } from "../charts/ShotChart";
import GameLines from "./GameLines";
import { Async, PlayerCell, TeamLogo } from "./ui";
import type {
  BoxScoreRow,
  ClosingLine,
  FlowPlay,
  GamePropRow,
  GameRow,
  GameShotsResponse,
  MarketPropRow,
  ShotDefenseResponse,
} from "../lib/api";
import { moneylineLabel, propLabel, spreadLabel, useQuery } from "../lib/api";
import { madeAttempted, num, pct, signed, timeOf } from "../lib/format";

type Tab = "lines" | "props" | "shots" | "defense" | "box" | "flow";

const TABS: { id: Tab; label: string }[] = [
  { id: "lines", label: "Team lines" },
  { id: "props", label: "Player props" },
  { id: "shots", label: "Shot charts" },
  { id: "defense", label: "Shot defense" },
  { id: "box", label: "Box score" },
  { id: "flow", label: "Score flow" },
];

/* --------------------------------------------------------------- tabs --- */

/** An empty tab explains itself. "Nothing recorded" reads as a broken feature;
    these gaps have causes, and naming them is the difference. */
function NotCovered({ what, why }: { what: string; why: string }) {
  return (
    <p className="empty">
      No {what} recorded for this game.
      <br />
      <span style={{ fontSize: "var(--t-xs)" }}>{why}</span>
    </p>
  );
}

/** Live props from Kalshi and Polymarket.
 *
 * These are the props that still arrive: the venues are free and unmetered and
 * captured every half hour, while the sportsbook prop feed is paid and lapsed
 * on 2026-08-03. Both are normalised to a line and the probability of going
 * over it, so a Kalshi threshold ("15+") and a Polymarket O/U sit in one table.
 */
function MarketProps({ gameId }: { gameId: number }) {
  const query = useQuery<{ props: MarketPropRow[] }>(
    `/lines/market-props?game_id=${gameId}&limit=300`,
  );
  if (!query.loading && !query.error && !query.data?.props.length) return null;
  return (
    <div style={{ marginBottom: "var(--s-5)" }}>
      <h4 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
        Prediction markets <span className="muted">· live</span>
      </h4>
      <Async query={query} empty={(data) => data.props.length === 0}>
        {(data) => (
          <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th className="name">Player</th>
                  <th>Market</th>
                  <th>Line</th>
                  <th>Over</th>
                  <th>Venue</th>
                </tr>
              </thead>
              <tbody>
                {data.props.map((row) => (
                  <tr key={`${row.provider}-${row.player_id}-${row.prop_type}-${row.line}`}>
                    <td className="name">
                      <PlayerCell playerId={row.player_id} name={row.full_name} />
                    </td>
                    <td>{propLabel(row.prop_type)}</td>
                    <td className="num">o{row.line}</td>
                    <td className="num">{pct(Number(row.over_probability))}</td>
                    <td className="muted">{row.provider}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </div>
  );
}

function PropsTab({ gameId }: { gameId: number }) {
  const query = useQuery<{ props: GamePropRow[] }>(`/games/${gameId}/props`);
  const hasSportsbook = !!query.data?.props.length;
  return (
    <>
      <MarketProps gameId={gameId} />
      {!query.loading && !query.error && !hasSportsbook ? (
        <NotCovered
          what="sportsbook prop lines"
          why="That feed is paid and its key lapsed on 2026-08-03. Prediction-market props above are free and still live."
        />
      ) : (
        <SportsbookProps query={query} />
      )}
    </>
  );
}

function SportsbookProps({
  query,
}: {
  query: { data: { props: GamePropRow[] } | undefined; error: Error | undefined; loading: boolean };
}) {
  return (
    <Async query={query} empty={(data) => data.props.length === 0}>
      {(data) => (
        <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th className="name">Player</th>
                <th>Team</th>
                <th>Market</th>
                <th>Line</th>
                <th>Actual</th>
                <th>Result</th>
                <th>Books</th>
              </tr>
            </thead>
            <tbody>
              {data.props.map((row) => {
                const line = Number(row.line);
                const settled = row.realized != null;
                const over = settled && row.realized! > line;
                const push = settled && row.realized === line;
                return (
                  <tr key={`${row.player_id}-${row.prop_type}`}>
                    <td className="name">
                      <PlayerCell playerId={row.player_id} name={row.full_name} />
                    </td>
                    <td>{row.team_abbr ?? "—"}</td>
                    <td>{propLabel(row.prop_type)}</td>
                    <td className="num">{row.line}</td>
                    <td className="num">{row.realized ?? "—"}</td>
                    <td>
                      {!settled ? (
                        <span className="muted">pending</span>
                      ) : push ? (
                        <span className="badge">push</span>
                      ) : (
                        <span className={over ? "badge badge--good" : "badge badge--bad"}>
                          {over ? "over" : "under"}
                        </span>
                      )}
                    </td>
                    <td className="num muted">{row.books}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Async>
  );
}

function TeamShots({ gameId, teamId, label }: { gameId: number; teamId: number; label: string }) {
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
      <Async query={query} empty={(data) => data.cells.length === 0}>
        {(data) => (
          <>
            <ShotChart
              cells={data.cells}
              binSize={data.bin_size}
              midpoint={data.points_per_attempt ?? 1}
              minAttempts={1}
            />
            <p className="prose" style={{ marginTop: "var(--s-2)" }}>
              {num(data.attempts)} attempts · {data.points_per_attempt?.toFixed(2) ?? "—"} pts/att
            </p>
          </>
        )}
      </Async>
    </div>
  );
}

function DefenseTab({ teamId, label, season }: { teamId: number; label: string; season: number }) {
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

function BoxTab({ gameId, awayAbbr, homeAbbr }: { gameId: number; awayAbbr: string; homeAbbr: string }) {
  const query = useQuery<{ players: BoxScoreRow[] }>(`/games/${gameId}/box`);
  return (
    <Async query={query} empty={(data) => data.players.length === 0}>
      {(data) =>
        [awayAbbr, homeAbbr].map((abbr) => {
          const rows = data.players.filter((row) => row.team_abbr === abbr);
          if (!rows.length) return null;
          return (
            <div key={abbr} style={{ marginBottom: "var(--s-4)" }}>
              <h4 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
                {abbr}
              </h4>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th className="name">Player</th>
                      <th>MIN</th>
                      <th>PTS</th>
                      <th>REB</th>
                      <th>AST</th>
                      <th>FG</th>
                      <th>3P</th>
                      <th>+/-</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.player_id}>
                        <td className="name">
                          <PlayerCell playerId={row.player_id} name={row.full_name} />
                        </td>
                        <td>{row.minutes ?? "—"}</td>
                        <td>{row.points ?? "—"}</td>
                        <td>{row.rebounds ?? "—"}</td>
                        <td>{row.assists ?? "—"}</td>
                        <td>{madeAttempted(row.field_goals_made, row.field_goals_attempted)}</td>
                        <td>
                          {madeAttempted(row.three_pointers_made, row.three_pointers_attempted)}
                        </td>
                        <td>{signed(row.plus_minus)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })
      }
    </Async>
  );
}

function FlowTab({ game }: { game: GameRow }) {
  const query = useQuery<{ plays: FlowPlay[] }>(`/games/${game.id}/flow`);
  return (
    <Async query={query} empty={(data) => data.plays.length < 2}>
      {(data) => (
        <GameFlow plays={data.plays} homeAbbr={game.home_abbr} awayAbbr={game.away_abbr} />
      )}
    </Async>
  );
}

/* --------------------------------------------------------------- panel --- */

export default function GamePanel({
  game,
  line,
  season,
}: {
  game: GameRow;
  line?: ClosingLine;
  season: number;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("lines");
  const final = game.status === "final";
  const homeWon = final && (game.home_score ?? 0) > (game.away_score ?? 0);

  return (
    <article className="panel">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        style={{
          width: "100%",
          display: "grid",
          gridTemplateColumns: "minmax(0,1fr) 150px 110px 28px",
          gap: "var(--s-4)",
          alignItems: "center",
          padding: "var(--s-3) var(--s-4)",
          background: "transparent",
          border: 0,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span style={{ display: "grid", gap: "var(--s-2)" }}>
          {[
            { id: game.away_team_id, name: game.away_team, score: game.away_score, win: final && !homeWon },
            { id: game.home_team_id, name: game.home_team, score: game.home_score, win: homeWon },
          ].map((side) => (
            <span key={side.id} style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
              <TeamLogo teamId={side.id} size="sm" />
              <span style={{ fontWeight: side.win ? 640 : 460 }}>{side.name}</span>
              <span className="num" style={{ marginLeft: "auto", fontWeight: side.win ? 640 : 460 }}>
                {final ? side.score : ""}
              </span>
            </span>
          ))}
        </span>

        <span style={{ fontSize: "var(--t-xs)", lineHeight: 1.5 }}>
          {line ? (
            <>
              <span className="num">
                {game.home_abbr} {spreadLabel(line.spread_home)}
              </span>
              <br />
              <span className="num muted">O/U {line.total ?? "—"}</span>
              <br />
              <span className="num muted">
                {moneylineLabel(line.moneyline_away)} / {moneylineLabel(line.moneyline_home)}
              </span>
            </>
          ) : (
            <span className="muted">no line recorded</span>
          )}
        </span>

        <span style={{ fontSize: "var(--t-xs)", textAlign: "right" }} className="muted">
          {final ? "Final" : timeOf(game.start_time)}
          <br />
          <Link to={`/games/${game.id}`} onClick={(event) => event.stopPropagation()}>
            full page →
          </Link>
        </span>

        <span
          aria-hidden
          className="muted"
          style={{
            justifySelf: "end",
            transition: "transform 0.15s",
            transform: open ? "rotate(90deg)" : "none",
          }}
        >
          ›
        </span>
      </button>

      {open && (
        <div style={{ borderTop: "1px solid var(--line)" }}>
          <div
            style={{
              display: "flex",
              gap: "var(--s-1)",
              padding: "var(--s-2) var(--s-4)",
              borderBottom: "1px solid var(--line)",
              overflowX: "auto",
            }}
          >
            {TABS.map((entry) => (
              <button
                key={entry.id}
                className="control"
                aria-pressed={tab === entry.id}
                onClick={() => setTab(entry.id)}
                style={{ height: 28, fontSize: "var(--t-xs)" }}
              >
                {entry.label}
              </button>
            ))}
          </div>

          <div style={{ padding: "var(--s-4)" }}>
            {tab === "lines" && (
              <GameLines gameId={game.id} homeAbbr={game.home_abbr} awayAbbr={game.away_abbr} />
            )}
            {tab === "props" && <PropsTab gameId={game.id} />}
            {tab === "shots" && (
              <div className="grid grid--2">
                <TeamShots gameId={game.id} teamId={game.away_team_id} label={game.away_team} />
                <TeamShots gameId={game.id} teamId={game.home_team_id} label={game.home_team} />
              </div>
            )}
            {tab === "defense" && (
              <>
                <div className="grid grid--2">
                  <DefenseTab teamId={game.away_team_id} label={game.away_team} season={season} />
                  <DefenseTab teamId={game.home_team_id} label={game.home_team} season={season} />
                </div>
                <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                  Season-long defensive profiles, not this game alone — one game is too few shots
                  to say anything about where a defence leaks.
                </p>
              </>
            )}
            {tab === "box" && (
              <BoxTab gameId={game.id} awayAbbr={game.away_abbr} homeAbbr={game.home_abbr} />
            )}
            {tab === "flow" && <FlowTab game={game} />}
          </div>

          {(tab === "shots" || tab === "defense") && (
            <div style={{ padding: "0 var(--s-4) var(--s-3)" }}>
              <ShotChartLegend />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

export { pct };
