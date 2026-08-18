import { useMemo } from "react";
import { useParams } from "react-router-dom";
import GameFlow from "../charts/GameFlow";
import { ShotChartLegend } from "../charts/ShotChart";
import GameLines from "../components/GameLines";
import { TeamShots, TeamShotDefense } from "../components/GameShotSections";
import HeadToHead from "../components/HeadToHead";
import LazySection from "../components/LazySection";
import Matchup from "../components/Matchup";
import PropTrends from "../components/PropTrends";
import ZoneMatchups from "../components/ZoneMatchups";
import { TimeSeries, type Series } from "../charts/primitives";
import { Async, Panel, PlayerCell, Section, Stat, TeamLogo } from "../components/ui";
import type { BoxScoreRow, FlowPlay, GameDetail as Game, MarketPrice, OddsRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { impliedFromAmerican, longDate, madeAttempted, pct, signed } from "../lib/format";
import { teamColor } from "../lib/teamColors";

function BoxScore({ rows, title }: { rows: BoxScoreRow[]; title: string }) {
  if (!rows.length) return null;
  return (
    <Panel title={title} flush>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Player</th>
              <th>MIN</th>
              <th>PTS</th>
              <th>REB</th>
              <th>AST</th>
              <th>STL</th>
              <th>BLK</th>
              <th>FG</th>
              <th>3P</th>
              <th>FT</th>
              <th>TO</th>
              <th>PF</th>
              <th>+/-</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.player_id}>
                <td>
                  <PlayerCell
                    playerId={row.player_id}
                    name={row.full_name}
                    meta={row.starter ? "starter" : undefined}
                  />
                </td>
                <td>{row.minutes ?? "—"}</td>
                <td>{row.points ?? "—"}</td>
                <td>{row.rebounds ?? "—"}</td>
                <td>{row.assists ?? "—"}</td>
                <td>{row.steals ?? "—"}</td>
                <td>{row.blocks ?? "—"}</td>
                <td>{madeAttempted(row.field_goals_made, row.field_goals_attempted)}</td>
                <td>{madeAttempted(row.three_pointers_made, row.three_pointers_attempted)}</td>
                <td>{madeAttempted(row.free_throws_made, row.free_throws_attempted)}</td>
                <td>{row.turnovers ?? "—"}</td>
                <td>{row.fouls ?? "—"}</td>
                <td>{signed(row.plus_minus)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export default function GameDetail() {
  const { gameId } = useParams();
  const game = useQuery<Game>(gameId ? `/games/${gameId}` : null);
  const box = useQuery<{ players: BoxScoreRow[] }>(gameId ? `/games/${gameId}/box` : null);
  const flow = useQuery<{ plays: FlowPlay[] }>(gameId ? `/games/${gameId}/flow` : null);
  const odds = useQuery<{ odds: OddsRow[] }>(gameId ? `/games/${gameId}/odds?limit=500` : null);
  const markets = useQuery<{ prices: MarketPrice[] }>(
    gameId ? `/games/${gameId}/markets?limit=500` : null,
  );

  /* Every venue normalised to one quantity: the probability the HOME team wins.
     Both sides of a market are quoted at the same instant and, once flipped,
     describe the same number twice -- so co-timestamped quotes are averaged to
     their midpoint. Plotting them as consecutive points draws a sawtooth that
     is an artefact of the bid/ask spread, not a price movement. */
  const series = useMemo<Series[]>(() => {
    const buckets: Record<string, Map<number, number[]>> = {
      book: new Map(),
      polymarket: new Map(),
      kalshi: new Map(),
    };

    for (const row of odds.data?.odds ?? []) {
      const value = impliedFromAmerican(row.moneyline_home_odds);
      if (value != null) buckets.book.set(new Date(row.captured_at).getTime(), [value]);
    }
    for (const row of markets.data?.prices ?? []) {
      const key = row.provider === "kalshi" ? "kalshi" : "polymarket";
      const raw = Number(row.implied_probability);
      if (!Number.isFinite(raw)) continue;
      const value = row.side === "home" ? raw : 1 - raw;
      const time = new Date(row.captured_at).getTime();
      buckets[key].set(time, [...(buckets[key].get(time) ?? []), value]);
    }

    const meta = [
      { key: "book", label: "Sportsbook", color: "var(--series-1)" },
      { key: "polymarket", label: "Polymarket", color: "var(--series-2)" },
      { key: "kalshi", label: "Kalshi", color: "var(--series-3)" },
    ];
    return meta.map((entry) => ({
      ...entry,
      points: [...buckets[entry.key]].map(([t, values]) => ({
        t,
        v: values.reduce((a, b) => a + b, 0) / values.length,
      })),
    }));
  }, [odds.data, markets.data]);

  return (
    <Async query={game}>
      {(data) => {
        const rows = box.data?.players ?? [];
        const away = rows.filter((row) => row.team_abbr === data.away_abbr);
        const home = rows.filter((row) => row.team_abbr === data.home_abbr);
        const final = data.status === "final";

        return (
          <>
            <Section
              title={`${data.away_team} at ${data.home_team}`}
              note={longDate(data.start_time)}
              level="h1"
            >
              <Panel
                accent={`linear-gradient(to right, ${teamColor(data.away_abbr)} 0 50%, ${teamColor(data.home_abbr)} 50% 100%)`}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto 1fr",
                    alignItems: "center",
                    gap: "var(--s-5)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "flex-end",
                      gap: "var(--s-3)",
                      textAlign: "right",
                    }}
                  >
                    <div>
                      <div className="team-mark" style={{ color: teamColor(data.away_abbr) }}>
                        {data.away_abbr}
                      </div>
                      <div className="muted" style={{ fontSize: "var(--t-xs)" }}>
                        {data.away_team}
                      </div>
                    </div>
                    <TeamLogo teamId={data.away_team_id} size="lg" />
                  </div>

                  <div style={{ textAlign: "center" }}>
                    <div
                      className="num"
                      style={{ fontFamily: "var(--t-display)", fontSize: "var(--t-4xl)", fontWeight: 700, lineHeight: 1 }}
                    >
                      {final ? `${data.away_score}–${data.home_score}` : "—"}
                    </div>
                    <div className="muted" style={{ fontSize: "var(--t-xs)", marginTop: "var(--s-1)" }}>
                      {final ? "Final" : data.status}
                    </div>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
                    <TeamLogo teamId={data.home_team_id} size="lg" />
                    <div>
                      <div className="team-mark" style={{ color: teamColor(data.home_abbr) }}>
                        {data.home_abbr}
                      </div>
                      <div className="muted" style={{ fontSize: "var(--t-xs)" }}>
                        {data.home_team}
                      </div>
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    gap: "var(--s-6)",
                    flexWrap: "wrap",
                    alignItems: "center",
                    justifyContent: "center",
                    marginTop: "var(--s-5)",
                  }}
                >
                  {data.venue_name && <Stat value={data.venue_name} label="Venue" />}
                  {data.attendance != null && (
                    <Stat value={data.attendance.toLocaleString()} label="Attendance" />
                  )}
                  {/* Preseason and All-Star games are largely unpriced by books
                      (AGENTS.md) — flagging it here explains a missing line
                      before a reader goes looking for one. */}
                  {data.season_type && data.season_type !== "regular-season" && (
                    <span className="badge badge--warn">{data.season_type.replace("-", " ")}</span>
                  )}
                </div>
              </Panel>
            </Section>

            {/* Context before result: record, form, rest and who is out is what
                makes the score above readable, so it goes first rather than
                being buried under charts a reader has to scroll past to reach it. */}
            <Section title="Matchup" note="Form, scoring, rest and injuries, cut at tip-off.">
              <Panel>
                <LazySection minHeight={480}>
                  <Matchup
                    gameId={data.id}
                    homeAbbr={data.home_abbr}
                    awayAbbr={data.away_abbr}
                    homeTeamId={data.home_team_id}
                    awayTeamId={data.away_team_id}
                    headingLevel="h3"
                  />
                </LazySection>
              </Panel>
            </Section>

            <Section
              title="Zone matchups"
              note="Rotation players on both sides whose own hot zones line up with the other defense's soft spots."
            >
              <Panel>
                <LazySection minHeight={280}>
                  <ZoneMatchups
                    gameId={data.id}
                    homeTeamId={data.home_team_id}
                    awayTeamId={data.away_team_id}
                    homeAbbr={data.home_abbr}
                    awayAbbr={data.away_abbr}
                  />
                </LazySection>
              </Panel>
            </Section>

            <Section title="Score flow" note="One point per scoring play, from play-by-play.">
              <Panel>
                <Async query={flow} empty={(d) => d.plays.length < 2}>
                  {(flowData) => (
                    <GameFlow
                      plays={flowData.plays}
                      homeAbbr={data.home_abbr}
                      awayAbbr={data.away_abbr}
                    />
                  )}
                </Async>
              </Panel>
            </Section>

            <Section
              title="Home win probability"
              note="Moneyline only, normalised across venues to one quantity."
            >
              <Panel>
                <div className="legend" style={{ marginBottom: "var(--s-3)" }}>
                  {series
                    .filter((entry) => entry.points.length)
                    .map((entry) => (
                      <span key={entry.key}>
                        <span className="swatch" style={{ background: entry.color }} />
                        {entry.label}
                      </span>
                    ))}
                </div>
                <TimeSeries
                  series={series}
                  formatValue={(value) => pct(value, 0)}
                  formatTime={(time) => new Date(time).toLocaleString()}
                />
              </Panel>
            </Section>

            <Section
              title="Prop trends"
              note="Live lines against how often each has actually cleared."
            >
              <Panel>
                <LazySection minHeight={420}>
                  <PropTrends gameId={data.id} />
                </LazySection>
              </Panel>
            </Section>

            <Section title="Head to head" note="Previous meetings between these two teams.">
              <Panel>
                <LazySection minHeight={240}>
                  <HeadToHead
                    homeTeamId={data.home_team_id}
                    awayTeamId={data.away_team_id}
                    homeAbbr={data.home_abbr}
                    awayAbbr={data.away_abbr}
                    before={data.start_time}
                  />
                </LazySection>
              </Panel>
            </Section>

            <Section
              title="Shot charts"
              note={final ? "Individual attempts, this game only." : "Recent form -- this game hasn't been played yet."}
            >
              <Panel>
                <LazySection minHeight={420}>
                  <div className="grid grid--2">
                    <TeamShots gameId={data.id} teamId={data.away_team_id} label={data.away_team} gameStatus={data.status} />
                    <TeamShots gameId={data.id} teamId={data.home_team_id} label={data.home_team} gameStatus={data.status} />
                  </div>
                </LazySection>
              </Panel>
            </Section>

            <Section
              title="Shot defense"
              note="Season profile, not this game alone — one game is far too few shots to say where a defence leaks."
            >
              <Panel tools={<ShotChartLegend />}>
                <LazySection minHeight={420}>
                  <div className="grid grid--2">
                    <TeamShotDefense teamId={data.away_team_id} label={data.away_team} season={data.season} />
                    <TeamShotDefense teamId={data.home_team_id} label={data.home_team} season={data.season} />
                  </div>
                </LazySection>
              </Panel>
            </Section>

            <Section title="Sportsbook lines" note="Consensus across books; two measures, two charts.">
              <div className="grid" style={{ gap: "var(--s-4)" }}>
                <GameLines
                  gameId={data.id}
                  homeAbbr={data.home_abbr}
                  awayAbbr={data.away_abbr}
                />
              </div>
            </Section>

            <Section title="Box score">
              <div className="grid" style={{ gap: "var(--s-4)" }}>
                <BoxScore rows={away} title={data.away_team} />
                <BoxScore rows={home} title={data.home_team} />
                {!rows.length && <Panel>
                  <p className="empty">No box score recorded for this game yet.</p>
                </Panel>}
              </div>
            </Section>
          </>
        );
      }}
    </Async>
  );
}
