/* One game, expandable into everything known about it.
 *
 * Collapsed by default and lazy: a day can hold five games, and eagerly loading
 * lines, props, shots, defence and a box score for each would be thirty
 * requests to render a scoreboard. Each tab fetches only when it is opened, and
 * only for the game that was opened.
 */

import { Link } from "react-router-dom";
import GameFlow from "../charts/GameFlow";
import GameShotPlot from "../charts/GameShotPlot";
import ShotChart, { ShotChartLegend } from "../charts/ShotChart";
import GameLines from "./GameLines";
import HeadToHead from "./HeadToHead";
import Matchup from "./Matchup";
import PropTrends from "./PropTrends";
import LazySection from "./LazySection";
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

/** A titled block inside a game. Sections read in order rather than hiding
    behind tabs; each mounts as it nears the viewport. */
function Block({
  title,
  hint,
  children,
  minHeight,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
  minHeight?: number;
}) {
  return (
    <section style={{ borderTop: "1px solid var(--line)", padding: "var(--s-4)" }}>
      <h4
        style={{
          fontSize: "var(--t-xs)",
          fontWeight: 660,
          letterSpacing: "0.07em",
          textTransform: "uppercase",
          color: "var(--ink-2)",
          marginBottom: "var(--s-3)",
        }}
      >
        {title}
        {hint && <span className="muted" style={{ marginLeft: "var(--s-2)", textTransform: "none", letterSpacing: 0 }}>{hint}</span>}
      </h4>
      <LazySection minHeight={minHeight ?? 260}>{children}</LazySection>
    </section>
  );
}

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
      <Async query={query} empty={(data) => (data.shots ?? []).length === 0}>
        {(data) => (
          <>
            {/* Individual attempts, not a heat grid: sixty-five shots binned
                onto a season-sized grid is one shot per cell and reads as
                noise. */}
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
  const final = game.status === "final";
  const homeWon = final && (game.home_score ?? 0) > (game.away_score ?? 0);

  return (
    <article className="panel">
      <header
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0,1fr) 150px 110px",
          gap: "var(--s-4)",
          alignItems: "center",
          padding: "var(--s-3) var(--s-4)",
        }}
      >
        <span style={{ display: "grid", gap: "var(--s-2)" }}>
          {[
            { id: game.away_team_id, name: game.away_team, score: game.away_score, win: final && !homeWon },
            { id: game.home_team_id, name: game.home_team, score: game.home_score, win: homeWon },
          ].map((side) => (
            <span key={side.id} style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
              <TeamLogo teamId={side.id} size="sm" />
              <Link to={`/teams/${side.id}`} style={{ fontWeight: side.win ? 640 : 460 }}>
                {side.name}
              </Link>
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
          <Link to={`/games/${game.id}`}>full page →</Link>
        </span>
      </header>

      {/* Everything, in reading order. No tabs: each block mounts as it nears
          the viewport, so scrolling is the only interaction needed. */}
      <Block title="Matchup" hint="form, scoring, rest and injuries" minHeight={480}>
        <Matchup
          gameId={game.id}
          homeAbbr={game.home_abbr}
          awayAbbr={game.away_abbr}
          homeTeamId={game.home_team_id}
          awayTeamId={game.away_team_id}
        />
      </Block>

      <Block title="Prop trends" hint="live lines vs how often they have been cleared" minHeight={420}>
        <PropTrends gameId={game.id} />
      </Block>

      <Block title="Head to head" hint="previous meetings" minHeight={240}>
        <HeadToHead
          homeTeamId={game.home_team_id}
          awayTeamId={game.away_team_id}
          homeAbbr={game.home_abbr}
          awayAbbr={game.away_abbr}
          before={game.start_time}
        />
      </Block>

      <Block title="Prop lines" minHeight={300}>
        <PropsTab gameId={game.id} />
      </Block>

      <Block title="Shot charts" minHeight={420}>
        <div className="grid grid--2">
          <TeamShots gameId={game.id} teamId={game.away_team_id} label={game.away_team} />
          <TeamShots gameId={game.id} teamId={game.home_team_id} label={game.home_team} />
        </div>
      </Block>

      <Block title="Shot defense" hint="season profile" minHeight={420}>
        <div className="grid grid--2">
          <DefenseTab teamId={game.away_team_id} label={game.away_team} season={season} />
          <DefenseTab teamId={game.home_team_id} label={game.home_team} season={season} />
        </div>
        <div style={{ marginTop: "var(--s-3)" }}>
          <ShotChartLegend />
        </div>
        <p className="prose" style={{ marginTop: "var(--s-2)" }}>
          Season-long, not this game alone — one game is far too few shots to say where a defence
          leaks.
        </p>
      </Block>

      <Block title="Team lines" minHeight={320}>
        <GameLines gameId={game.id} homeAbbr={game.home_abbr} awayAbbr={game.away_abbr} />
      </Block>

      <Block title="Score flow" minHeight={280}>
        <FlowTab game={game} />
      </Block>

      <Block title="Box score" minHeight={340}>
        <BoxTab gameId={game.id} awayAbbr={game.away_abbr} homeAbbr={game.home_abbr} />
      </Block>
    </article>
  );
}
