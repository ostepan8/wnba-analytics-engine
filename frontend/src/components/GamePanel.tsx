/* One game, expandable into everything known about it.
 *
 * Collapsed by default and lazy: a day can hold five games, and eagerly loading
 * lines, props, shots, defence and a box score for each would be thirty
 * requests to render a scoreboard. Each tab fetches only when it is opened, and
 * only for the game that was opened.
 */

import { Link } from "react-router-dom";
import GameFlow from "../charts/GameFlow";
import { ShotChartLegend } from "../charts/ShotChart";
import GameLines from "./GameLines";
import { TeamShots, TeamShotDefense } from "./GameShotSections";
import HeadToHead from "./HeadToHead";
import Matchup from "./Matchup";
import PropTrends from "./PropTrends";
import ZoneMatchups from "./ZoneMatchups";
import LazySection from "./LazySection";
import { Async, PlayerCell, TeamLogo } from "./ui";
import type { BoxScoreRow, ClosingLine, FlowPlay, GameRow, SlateTeam } from "../lib/api";
import { moneylineLabel, spreadLabel, useQuery } from "../lib/api";
import { madeAttempted, signed, timeOf } from "../lib/format";

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

/** Record, form and rest in one line, for the collapsed header.
 *
 * The card is the only thing most readers see, so the facts that decide whether
 * a game is worth opening belong on it rather than three sections down. */
function TeamLine({ team }: { team?: SlateTeam }) {
  const form = team?.form;
  if (!form || form.games == null) return null;

  const parts = [`${form.wins}-${form.losses}`];
  if (form.games_l10) parts.push(`L10 ${form.wins_l10}-${form.games_l10 - form.wins_l10!}`);
  if (form.points_for) parts.push(`${form.points_for} PF`);
  if (form.points_against) parts.push(`${form.points_against} PA`);
  if (team?.rest_days != null) parts.push(`${team.rest_days}d rest`);
  if (team && team.out.length > 0) parts.push(`${team.out.length} out`);

  return (
    <span className="muted" style={{ fontSize: "var(--t-xs)" }}>
      {parts.join(" · ")}
    </span>
  );
}

export default function GamePanel({
  game,
  line,
  season,
  context,
}: {
  game: GameRow;
  line?: ClosingLine;
  season: number;
  /** Both sides' form, rest and injuries, already fetched for the whole slate. */
  context?: Record<string, SlateTeam>;
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
              <span style={{ display: "grid", minWidth: 0 }}>
                <Link to={`/teams/${side.id}`} style={{ fontWeight: side.win ? 640 : 460 }}>
                  {side.name}
                </Link>
                <TeamLine team={context?.[String(side.id)]} />
              </span>
              <span
                className="num"
                style={{
                  marginLeft: "auto",
                  fontFamily: "var(--t-display)",
                  fontSize: "20px",
                  fontWeight: side.win ? 700 : 500,
                  color: side.win ? "var(--ink)" : "var(--ink-muted)",
                }}
              >
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

      <Block title="Zone matchups" hint="hot zones vs the other side's soft spots" minHeight={280}>
        <ZoneMatchups
          gameId={game.id}
          homeTeamId={game.home_team_id}
          awayTeamId={game.away_team_id}
          homeAbbr={game.home_abbr}
          awayAbbr={game.away_abbr}
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

      <Block title="Shot charts" minHeight={420}>
        <div className="grid grid--2">
          <TeamShots gameId={game.id} teamId={game.away_team_id} label={game.away_team} gameStatus={game.status} />
          <TeamShots gameId={game.id} teamId={game.home_team_id} label={game.home_team} gameStatus={game.status} />
        </div>
      </Block>

      <Block title="Shot defense" hint="season profile" minHeight={420}>
        <div className="grid grid--2">
          <TeamShotDefense teamId={game.away_team_id} label={game.away_team} season={season} />
          <TeamShotDefense teamId={game.home_team_id} label={game.home_team} season={season} />
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
