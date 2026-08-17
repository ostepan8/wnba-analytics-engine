import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ShotChart, { ShotChartLegend } from "../charts/ShotChart";
import {
  Async,
  Panel,
  PlayerCell,
  Section,
  SeasonPicker,
  Stat,
  TeamLogo,
} from "../components/ui";
import type { RosterRow, ScheduleRow, ShotChartResponse, TeamRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, avg, num, pct, rate, seasonOptions, shortDate } from "../lib/format";

interface TeamResponse {
  season: number;
  team: TeamRow;
  roster: RosterRow[];
  schedule: ScheduleRow[];
}

function resultOf(game: ScheduleRow) {
  if (game.status !== "final" || game.home_score == null || game.away_score == null) return null;
  const ours = game.is_home ? game.home_score : game.away_score;
  const theirs = game.is_home ? game.away_score : game.home_score;
  return { won: ours > theirs, line: `${ours}-${theirs}` };
}

export default function TeamDetail() {
  const { teamId } = useParams();
  const [season, setSeason] = useState(CURRENT_SEASON);
  const seasons = useMemo(() => seasonOptions(), []);

  const team = useQuery<TeamResponse>(teamId ? `/teams/${teamId}?season=${season}` : null);
  const shots = useQuery<ShotChartResponse>(
    teamId ? `/shots?season=${season}&team_id=${teamId}` : null,
  );

  return (
    <Async query={team}>
      {(data) => (
        <>
          <Section title={data.team.name} note={data.team.conference ?? undefined}>
            <Panel tools={<SeasonPicker season={season} seasons={seasons} onChange={setSeason} />}>
              <div style={{ display: "flex", gap: "var(--s-5)", alignItems: "center", flexWrap: "wrap" }}>
                <TeamLogo teamId={data.team.id} size="lg" />
                <Stat
                  value={`${data.team.wins ?? "—"}-${data.team.losses ?? "—"}`}
                  label="Record"
                  detail={rate(data.team.win_percentage)}
                />
                <Stat value={data.team.home_record ?? "—"} label="Home" />
                <Stat value={data.team.away_record ?? "—"} label="Away" />
                <Stat
                  value={data.team.playoff_seed ? `#${data.team.playoff_seed}` : "—"}
                  label="Seed"
                  detail={data.team.games_behind ? `${data.team.games_behind} GB` : undefined}
                />
              </div>
            </Panel>
          </Section>

          <div className="grid grid--sidebar">
            <Section title="Roster" note="Ordered by minutes — the rotation, top to bottom.">
              <Panel flush>
                {data.roster.length === 0 ? (
                  <p className="empty">No games recorded this season.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Player</th>
                          <th>Pos</th>
                          <th>G</th>
                          <th>MIN</th>
                          <th>PTS</th>
                          <th>REB</th>
                          <th>AST</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.roster.map((player) => (
                          <tr key={player.player_id}>
                            <td>
                              <PlayerCell playerId={player.player_id} name={player.full_name} />
                            </td>
                            <td>{player.position ?? "—"}</td>
                            <td>{player.games_played}</td>
                            <td>{avg(player.minutes)}</td>
                            <td>{avg(player.points)}</td>
                            <td>{avg(player.rebounds)}</td>
                            <td>{avg(player.assists)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </Section>

            <Section title="Schedule">
              <Panel flush>
                {data.schedule.length === 0 ? (
                  <p className="empty">No games scheduled.</p>
                ) : (
                  <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Opponent</th>
                          <th>Result</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.schedule.map((game) => {
                          const result = resultOf(game);
                          return (
                            <tr key={game.id}>
                              <td>
                                <Link to={`/games/${game.id}`}>{shortDate(game.start_time)}</Link>
                              </td>
                              <td>
                                {game.is_home ? "vs " : "@ "}
                                <Link to={`/teams/${game.opponent_id}`}>{game.opponent_abbr}</Link>
                              </td>
                              <td>
                                {result ? (
                                  <span className={result.won ? "badge badge--good" : "badge badge--bad"}>
                                    {result.won ? "W" : "L"} {result.line}
                                  </span>
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </Section>
          </div>

          <Section title="Shot profile">
            <Panel title="Where this team shoots" tools={<ShotChartLegend />}>
              <div className="grid grid--2">
                <Async query={shots} empty={(d) => d.cells.length === 0}>
                  {(shotData) => (
                    <ShotChart
                      cells={shotData.cells}
                      binSize={shotData.bin_size}
                      midpoint={shotData.points_per_attempt ?? 1}
                      minAttempts={2}
                    />
                  )}
                </Async>
                <Async query={shots}>
                  {(shotData) => (
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Zone</th>
                            <th>Att</th>
                            <th>FG%</th>
                          </tr>
                        </thead>
                        <tbody>
                          {shotData.zones
                            .filter((zone) => zone.attempts >= 5)
                            .map((zone) => (
                              <tr key={zone.zone}>
                                <td>{zone.zone}</td>
                                <td>{num(zone.attempts)}</td>
                                <td>{pct(zone.makes / zone.attempts)}</td>
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
        </>
      )}
    </Async>
  );
}
