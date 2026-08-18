import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ShotChart, { ShotChartLegend } from "../charts/ShotChart";
import PropLines from "../components/PropLines";
import {
  Async,
  Panel,
  PlayerAvatar,
  PlayerCell,
  Section,
  SeasonPicker,
  Stat,
} from "../components/ui";
import type {
  EfficiencyRow,
  GameLogRow,
  PlayerProfile,
  PlayerSeason,
  ShotChartResponse,
  ShotDefenseResponse,
} from "../lib/api";
import { useQuery } from "../lib/api";
import {
  CURRENT_SEASON,
  avg,
  madeAttempted,
  num,
  pct,
  rate,
  seasonOptions,
  shortDate,
  signed,
} from "../lib/format";
import { teamColor } from "../lib/teamColors";

interface PlayerResponse {
  player: PlayerProfile;
  seasons: PlayerSeason[];
  game_log: GameLogRow[];
}

export default function PlayerDetail() {
  const { playerId } = useParams();
  const [season, setSeason] = useState(CURRENT_SEASON);
  const seasons = useMemo(() => seasonOptions(), []);

  const player = useQuery<PlayerResponse>(playerId ? `/players/${playerId}` : null);
  const shots = useQuery<ShotChartResponse>(
    playerId ? `/shots?season=${season}&player_id=${playerId}&bin_size=25` : null,
  );
  // `/efficiency` has no player_id filter, so the league table is fetched and
  // this one row picked out client-side. min_games=1 on purpose: the league
  // leaderboard uses 10 to keep its ranking meaningful, but a single player's
  // own profile should show their number even in a three-game season, not
  // silently omit it because they fell under someone else's cutoff.
  const efficiency = useQuery<{ players: EfficiencyRow[] }>(
    playerId ? `/efficiency?season=${season}&min_games=1&limit=500` : null,
  );
  // Which team to ask "who shoots well against them" about isn't known from
  // the URL -- it only exists once the player's own season row has loaded, so
  // this reads player.data directly rather than through the Async below.
  const teamId =
    player.data?.seasons.find((row) => row.season === season)?.team_id ??
    player.data?.seasons[0]?.team_id ??
    null;
  const shotDefense = useQuery<ShotDefenseResponse>(
    teamId ? `/teams/${teamId}/defense?season=${season}` : null,
  );

  return (
    <Async query={player}>
      {(data) => {
        const current =
          data.seasons.find((row) => row.season === season) ?? data.seasons[0] ?? null;
        const log = data.game_log.filter((row) => row.season === season).slice(0, 25);
        const efficiencyRow =
          efficiency.data?.players.find((row) => String(row.player_id) === playerId) ?? null;

        return (
          <>
            <Section title={data.player.full_name}>
              <Panel
                accent={teamColor(current?.team_abbr)}
                tools={<SeasonPicker season={season} seasons={seasons} onChange={setSeason} />}
              >
                <div
                  style={{
                    display: "flex",
                    gap: "var(--s-5)",
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <PlayerAvatar playerId={data.player.player_id} size="xl" />
                  <div>
                    <p className="muted" style={{ fontSize: "var(--t-sm)" }}>
                      {[
                        data.player.position,
                        data.player.jersey_number ? `#${data.player.jersey_number}` : null,
                        data.player.height,
                        data.player.college,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "No profile details recorded"}
                    </p>
                  </div>
                  {current && (
                    <>
                      <Stat value={avg(current.points)} label="PPG" detail={`${current.games_played} games`} />
                      <Stat value={avg(current.rebounds)} label="RPG" />
                      <Stat value={avg(current.assists)} label="APG" />
                      <Stat value={rate(current.field_goal_pct)} label="FG%" />
                      <Stat value={rate(current.three_point_pct)} label="3P%" />
                    </>
                  )}
                  {efficiencyRow && (
                    <>
                      <Stat
                        value={pct(efficiencyRow.usage_pct)}
                        label="USG%"
                        detail="share of team possessions used"
                      />
                      <Stat
                        value={pct(efficiencyRow.true_shooting)}
                        label="TS%"
                        detail="value, not just volume"
                      />
                      <Stat
                        value={signed(efficiencyRow.net_rating, 1)}
                        label="Net Rtg"
                        detail="per 100 possessions on court"
                      />
                    </>
                  )}
                </div>
              </Panel>
            </Section>

            <Section title="Career" note="Per-game averages by season.">
              <Panel flush>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Season</th>
                        <th>Team</th>
                        <th>G</th>
                        <th>MIN</th>
                        <th>PTS</th>
                        <th>REB</th>
                        <th>AST</th>
                        <th>STL</th>
                        <th>BLK</th>
                        <th>FG%</th>
                        <th>3P%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.seasons.map((row) => (
                        <tr key={row.season}>
                          <td>{row.season}</td>
                          <td>{row.team_abbr ?? "—"}</td>
                          <td>{row.games_played}</td>
                          <td>{avg(row.minutes)}</td>
                          <td>{avg(row.points)}</td>
                          <td>{avg(row.rebounds)}</td>
                          <td>{avg(row.assists)}</td>
                          <td>{avg(row.steals)}</td>
                          <td>{avg(row.blocks)}</td>
                          <td>{rate(row.field_goal_pct)}</td>
                          <td>{rate(row.three_point_pct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </Section>

            <div className="grid grid--sidebar">
              <Section title="Shot chart" note={`${season} season.`}>
                <Panel tools={<ShotChartLegend />}>
                  <Async query={shots} empty={(shotData) => shotData.cells.length === 0}>
                    {(shotData) => (
                      <>
                        <ShotChart
                          cells={shotData.cells}
                          binSize={shotData.bin_size}
                          midpoint={shotData.points_per_attempt ?? 1}
                          minAttempts={1}
                        />
                        <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                          {num(shotData.attempts)} attempts ·{" "}
                          {shotData.points_per_attempt?.toFixed(2) ?? "—"} points per attempt.
                          Colour compares each spot to the league average, so a cold rim is
                          genuinely cold rather than merely a low percentage.
                        </p>
                      </>
                    )}
                  </Async>
                </Panel>
              </Section>

              <Section title="Zones">
                <Panel flush>
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
                              .filter((zone) => zone.attempts >= 3)
                              .map((zone) => (
                                <tr key={zone.zone}>
                                  <td>{zone.zone}</td>
                                  <td>{zone.attempts}</td>
                                  <td>{pct(zone.makes / zone.attempts)}</td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Async>
                </Panel>
              </Section>

              <Section title="Shot defense" note={`How ${current?.team_abbr ?? "their team"} allows shots, ${season}.`}>
                <Panel tools={<ShotChartLegend />}>
                  <Async query={shotDefense} empty={(shotData) => shotData.cells.length === 0}>
                    {(shotData) => (
                      <>
                        <ShotChart
                          cells={shotData.cells}
                          binSize={shotData.bin_size}
                          midpoint={shotData.points_per_attempt ?? 1}
                          minAttempts={2}
                        />
                        <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                          Where opponents shoot against this player&apos;s team, not this player&apos;s
                          own defense specifically — shot data records who took a shot, never who
                          guarded it.
                        </p>
                      </>
                    )}
                  </Async>
                </Panel>
              </Section>

              <Section title="Who's gone off" note="Opposing shooters, ranked by points scored.">
                <Panel flush>
                  <Async query={shotDefense} empty={(shotData) => shotData.by_player.length === 0}>
                    {(shotData) => (
                      <div className="table-wrap">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Player</th>
                              <th>Att</th>
                              <th>FG%</th>
                              <th>PTS</th>
                            </tr>
                          </thead>
                          <tbody>
                            {shotData.by_player.map((row) => (
                              <tr key={row.player_id}>
                                <td>
                                  <PlayerCell playerId={row.player_id} name={row.full_name} />
                                </td>
                                <td>{row.attempts}</td>
                                <td>{pct(row.makes / row.attempts)}</td>
                                <td>{row.points}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Async>
                </Panel>
              </Section>
            </div>

            <Section
              title="Betting lines"
              note="Where the market set the number, and what happened."
            >
              <PropLines playerId={data.player.player_id} />
            </Section>

            <Section title="Game log" note={`Most recent ${season} appearances.`}>
              <Panel flush>
                {log.length === 0 ? (
                  <p className="empty">No {season} appearances recorded.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Opp</th>
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
                        {log.map((row) => (
                          <tr key={row.game_id}>
                            <td>
                              <Link to={`/games/${row.game_id}`}>{shortDate(row.start_time)}</Link>
                            </td>
                            <td>
                              {row.is_home ? "vs " : "@ "}
                              <Link to={`/teams/${row.opponent_id}`}>{row.opponent_abbr}</Link>
                            </td>
                            <td>{row.minutes ?? "—"}</td>
                            <td>{row.points ?? "—"}</td>
                            <td>{row.rebounds ?? "—"}</td>
                            <td>{row.assists ?? "—"}</td>
                            <td>
                              {madeAttempted(row.field_goals_made, row.field_goals_attempted)}
                            </td>
                            <td>
                              {madeAttempted(
                                row.three_pointers_made,
                                row.three_pointers_attempted,
                              )}
                            </td>
                            <td>{signed(row.plus_minus)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </Section>
          </>
        );
      }}
    </Async>
  );
}
