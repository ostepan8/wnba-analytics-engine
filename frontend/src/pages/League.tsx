import { useMemo, useState } from "react";
import ShotChart, { ShotChartLegend } from "../charts/ShotChart";
import { BarList } from "../charts/primitives";
import { Async, Panel, RaceBadge, Section, SeasonPicker, Stat, TeamCell } from "../components/ui";
import type {
  DatasetSummary,
  EfficiencyRow,
  LeaderRow,
  ShotChartResponse,
  StandingRow,
} from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, avg, num, pct, rate, relativeTime, seasonOptions } from "../lib/format";
import EfficiencyScatter from "../charts/EfficiencyScatter";

/** Grouped by conference, so "GB" here is the provider's conference-relative
 *  figure -- the right read inside a table already scoped to one conference.
 *  "GB8" is the league-wide games-behind-the-cut and Status is the same
 *  RaceBadge Teams.tsx uses for the combined table: a conference table alone
 *  answers "how does this team compare to its own conference", never "is it
 *  actually going to make the playoffs" -- the WNBA's cut is league-wide, not
 *  per-conference, so that second question needs the league-wide fields. */
function StandingsTable({ rows }: { rows: StandingRow[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Team</th>
            <th>W</th>
            <th>L</th>
            <th>PCT</th>
            <th>GB</th>
            <th title="Games behind the last league-wide playoff spot">GB8</th>
            <th>L10</th>
            <th>Home</th>
            <th>Away</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.team_id}>
              <td>
                <TeamCell teamId={row.team_id} name={row.name} />
              </td>
              <td>{row.wins ?? "—"}</td>
              <td>{row.losses ?? "—"}</td>
              <td>{rate(row.win_percentage)}</td>
              <td>{row.games_behind ?? "—"}</td>
              <td>{row.in_playoff_position ? "—" : row.games_behind_playoff}</td>
              <td>
                {row.last10_wins}-{row.last10_losses}
              </td>
              <td>{row.home_record ?? "—"}</td>
              <td>{row.away_record ?? "—"}</td>
              <td>
                <RaceBadge status={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function League() {
  const [season, setSeason] = useState(CURRENT_SEASON);
  const seasons = useMemo(() => seasonOptions(), []);

  const standings = useQuery<{ standings: StandingRow[]; race_open: boolean }>(
    `/standings?season=${season}`,
  );
  const leaders = useQuery<{ leaders: LeaderRow[] }>(`/leaders?season=${season}&limit=10`);
  const shots = useQuery<ShotChartResponse>(`/shots?season=${season}`);
  const efficiency = useQuery<{ players: EfficiencyRow[] }>(
    `/efficiency?season=${season}&min_games=10&limit=200`,
  );
  const summary = useQuery<DatasetSummary>("/summary");

  const conferences = useMemo(() => {
    const rows = standings.data?.standings ?? [];
    const grouped = new Map<string, StandingRow[]>();
    for (const row of rows) {
      const key = row.conference ?? "League";
      grouped.set(key, [...(grouped.get(key) ?? []), row]);
    }
    return [...grouped.entries()];
  }, [standings.data]);

  return (
    <>
      {/* Full width, stacked, not the side-by-side pair this used to be: the
          added GB8/L10/Status columns make each table too wide to share a
          row without hiding a column behind horizontal scroll, and a
          standings table is a list read top to bottom, not something that
          benefits from sitting beside its twin. */}
      <Section
        title={`${season} season`}
        note="Standings, scoring, and league-wide shooting."
        level="h1"
      >
        <div style={{ display: "grid", gap: "var(--s-4)" }}>
          <Async query={standings} empty={(d) => d.standings.length === 0}>
            {(data) =>
              conferences.map(([conference, rows]) => (
                <Panel
                  key={conference}
                  title={conference}
                  hint={data.race_open ? "Race open" : "Field decided"}
                  flush
                >
                  <StandingsTable rows={rows} />
                </Panel>
              ))
            }
          </Async>
        </div>
      </Section>

      <Section title="Shot profile" note="Coloured by points per attempt, sized by volume.">
        <Panel
          title="Where the league shoots"
          tools={
            <>
              <ShotChartLegend />
              <SeasonPicker season={season} seasons={seasons} onChange={setSeason} />
            </>
          }
        >
          <div className="grid grid--2">
            <Async query={shots} empty={(d) => d.cells.length === 0}>
              {(data) => (
                <ShotChart
                  cells={data.cells}
                  binSize={data.bin_size}
                  midpoint={data.points_per_attempt ?? 1}
                />
              )}
            </Async>
            <Async query={shots}>
              {(data) => (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Zone</th>
                        <th>Att</th>
                        <th>FG%</th>
                        <th>Dist</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.zones
                        .filter((zone) => zone.attempts >= 5)
                        .map((zone) => (
                          <tr key={zone.zone}>
                            <td>{zone.zone}</td>
                            <td>{num(zone.attempts)}</td>
                            <td>{pct(zone.makes / zone.attempts)}</td>
                            <td>{zone.avg_distance ?? "—"} ft</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Async>
          </div>
        </Panel>
      </Section>

      <div className="grid grid--2">
        <Section title="Scoring leaders" note="Points per game.">
          <Panel>
            <Async query={leaders} empty={(d) => d.leaders.length === 0}>
              {(data) => (
                <BarList
                  rows={data.leaders.map((row) => ({
                    key: row.player_id,
                    label: row.full_name,
                    value: Number(row.points),
                  }))}
                />
              )}
            </Async>
          </Panel>
        </Section>

        <Section title="Usage vs efficiency" note="Volume separated from value.">
          <Panel>
            <Async query={efficiency} empty={(d) => d.players.length === 0}>
              {(data) => <EfficiencyScatter players={data.players} />}
            </Async>
          </Panel>
        </Section>
      </div>

      <Section title="Dataset" note="What has been collected, and how current it is.">
        <Panel>
          <Async query={summary}>
            {(data) => (
              <div className="grid grid--4">
                <Stat value={num(data.games)} label="Games" detail={`${data.games_final} final`} />
                <Stat
                  value={num(data.market_price_snapshots)}
                  label="Price snapshots"
                  detail={relativeTime(data.latest_market_price)}
                />
                <Stat
                  value={num(data.sportsbook_game_odds)}
                  label="Sportsbook rows"
                  detail={relativeTime(data.latest_sportsbook_odds)}
                />
                <Stat
                  value={num(data.players)}
                  label="Players"
                  detail={`${data.teams} teams · ${avg(
                    (new Date(data.latest_game).getFullYear() -
                      new Date(data.earliest_game).getFullYear()) as unknown as number,
                  )} seasons`}
                />
              </div>
            )}
          </Async>
        </Panel>
      </Section>
    </>
  );
}
