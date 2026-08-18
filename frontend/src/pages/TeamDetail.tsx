import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ShotChart, { ShotChartLegend } from "../charts/ShotChart";
import {
  Async,
  Panel,
  PlayerCell,
  RaceBadge,
  Section,
  SeasonPicker,
  SortTh,
  Stat,
  TeamLogo,
} from "../components/ui";
import type {
  DefenseByPositionRow,
  RosterRow,
  ScheduleRow,
  ShotChartResponse,
  ShotDefenseResponse,
  TeamBettingRecord,
  TeamRow,
} from "../lib/api";
import { useQuery, spreadLabel } from "../lib/api";
import { CURRENT_SEASON, avg, num, pct, rate, seasonOptions, shortDate } from "../lib/format";
import { teamColor } from "../lib/teamColors";
import { useSort } from "../lib/useSort";

type RosterSortColumn =
  | "games_played"
  | "minutes"
  | "points"
  | "rebounds"
  | "assists"
  | "steals"
  | "blocks";
type ScheduleSortColumn = "start_time" | "spread" | "total";

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
  const betting = useQuery<{ record: TeamBettingRecord | null }>(
    teamId ? `/teams/${teamId}/betting?season=${season}` : null,
  );
  const defense = useQuery<{ rows: DefenseByPositionRow[] }>(
    teamId ? `/defense/by-position?season=${season}&team_id=${teamId}` : null,
  );
  const shotDefense = useQuery<ShotDefenseResponse>(
    teamId ? `/teams/${teamId}/defense?season=${season}&bin_size=20` : null,
  );

  // Called here, not inside the page's outer Async render-prop: that render
  // prop only runs once `team` has loaded, and a hook called conditionally
  // like that breaks React's hook-order rule between the skeleton and the
  // loaded render.
  const rosterAccessor = useCallback((row: RosterRow, key: RosterSortColumn) => row[key], []);
  const roster = useSort<RosterRow, RosterSortColumn>(
    team.data?.roster ?? [],
    rosterAccessor,
    "minutes",
  );
  // No initial column: the schedule starts in the order the API returns it
  // (chronological) and only reorders once someone actually clicks a header.
  const scheduleAccessor = useCallback(
    (row: ScheduleRow, key: ScheduleSortColumn) => row[key],
    [],
  );
  const schedule = useSort<ScheduleRow, ScheduleSortColumn>(
    team.data?.schedule ?? [],
    scheduleAccessor,
  );

  return (
    <Async query={team}>
      {(data) => (
        <>
          <Section title={data.team.name} note={data.team.conference ?? undefined} level="h1">
            <Panel
              accent={teamColor(data.team.abbreviation)}
              tools={<SeasonPicker season={season} seasons={seasons} onChange={setSeason} />}
            >
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
                  value={data.team.standing?.seed ? `#${data.team.standing.seed}` : "—"}
                  label="League seed"
                  detail={
                    data.team.standing?.games_behind_leader
                      ? `${data.team.standing.games_behind_leader} GB of the league`
                      : data.team.standing?.seed === 1
                        ? "league leader"
                        : undefined
                  }
                />
                <Stat
                  value={
                    data.team.standing?.conference_seed
                      ? `#${data.team.standing.conference_seed}`
                      : data.team.conference_seed
                        ? `#${data.team.conference_seed}`
                        : "—"
                  }
                  label="Conference seed"
                  detail={data.team.conference?.replace(" Conference", "") ?? undefined}
                />
                {data.team.standing && (
                  <div>
                    <span
                      className="stat__label"
                      style={{ display: "block", marginBottom: "var(--s-1)" }}
                    >
                      Playoff race
                    </span>
                    <RaceBadge status={data.team.standing} />
                  </div>
                )}
              </div>
            </Panel>
          </Section>

          <Section title="Against the number" note="Closing consensus; pushes excluded.">
            <Panel>
              <Async query={betting} empty={(d) => !d.record || d.record.spread_games === 0}>
                {(d) => {
                  const r = d.record!;
                  const ats = r.covers + r.non_covers;
                  const ou = r.overs + r.unders;
                  return (
                    <div className="grid grid--4">
                      <Stat
                        value={`${r.covers}-${r.non_covers}`}
                        label="Against the spread"
                        detail={ats ? `${pct(r.covers / ats)} cover rate` : undefined}
                      />
                      <Stat
                        value={`${r.overs}-${r.unders}`}
                        label="Over / under"
                        detail={ou ? `${pct(r.overs / ou)} went over` : undefined}
                      />
                      <Stat value={r.avg_spread ?? "—"} label="Avg spread" />
                      <Stat value={r.avg_total ?? "—"} label="Avg total" />
                    </div>
                  );
                }}
              </Async>
            </Panel>
          </Section>

          <div className="grid grid--2">
            <Section
              title="Roster"
              note="Ordered by minutes — the rotation, top to bottom. Click a column to re-sort."
            >
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
                          <SortTh
                            label="G"
                            column="games_played"
                            active={roster.sortKey === "games_played"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                          <SortTh
                            label="MIN"
                            column="minutes"
                            active={roster.sortKey === "minutes"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                          <SortTh
                            label="PTS"
                            column="points"
                            active={roster.sortKey === "points"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                          <SortTh
                            label="REB"
                            column="rebounds"
                            active={roster.sortKey === "rebounds"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                          <SortTh
                            label="AST"
                            column="assists"
                            active={roster.sortKey === "assists"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                          <SortTh
                            label="STL"
                            column="steals"
                            active={roster.sortKey === "steals"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                          <SortTh
                            label="BLK"
                            column="blocks"
                            active={roster.sortKey === "blocks"}
                            direction={roster.direction}
                            onSort={roster.toggleSort}
                          />
                        </tr>
                      </thead>
                      <tbody>
                        {roster.sorted.map((player) => (
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
                            <td>{avg(player.steals)}</td>
                            <td>{avg(player.blocks)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </Section>

            <Section
              title="Schedule"
              note="With the closing number each game was played to — click a column to re-sort."
            >
              <Panel flush>
                {data.schedule.length === 0 ? (
                  <p className="empty">No games scheduled.</p>
                ) : (
                  <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
                    <table className="table">
                      <thead>
                        <tr>
                          <SortTh
                            label="Date"
                            column="start_time"
                            active={schedule.sortKey === "start_time"}
                            direction={schedule.direction}
                            onSort={schedule.toggleSort}
                          />
                          <th>Opponent</th>
                          <th>Result</th>
                          <SortTh
                            label="Spread"
                            column="spread"
                            active={schedule.sortKey === "spread"}
                            direction={schedule.direction}
                            onSort={schedule.toggleSort}
                          />
                          <th>ATS</th>
                          <SortTh
                            label="Total"
                            column="total"
                            active={schedule.sortKey === "total"}
                            direction={schedule.direction}
                            onSort={schedule.toggleSort}
                          />
                          <th>O/U</th>
                        </tr>
                      </thead>
                      <tbody>
                        {schedule.sorted.map((game) => {
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
                              <td className="num">{spreadLabel(game.spread)}</td>
                              <td>
                                {game.covered === null ? (
                                  <span className="muted">—</span>
                                ) : (
                                  <span
                                    className={game.covered ? "badge badge--good" : "badge badge--bad"}
                                  >
                                    {game.covered ? "cover" : "no"}
                                  </span>
                                )}
                              </td>
                              <td className="num">{game.total ?? "—"}</td>
                              <td>
                                {game.went_over === null ? (
                                  <span className="muted">—</span>
                                ) : (
                                  <span className="badge">{game.went_over ? "over" : "under"}</span>
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

          <Section
            title="Defense by position"
            note="What opponents average against this team, per player-game."
          >
            <Panel>
              <Async query={defense} empty={(d) => d.rows.length === 0}>
                {(d) => (
                  <>
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th className="name">Position</th>
                            <th>Opp games</th>
                            <th>PTS allowed</th>
                            <th title="1 = stingiest in the league">Rank</th>
                            <th>REB allowed</th>
                            <th>AST allowed</th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.rows.map((row) => (
                            <tr key={row.position}>
                              <td className="name">{row.position}</td>
                              <td className="num">{row.games}</td>
                              <td className="num">{row.points_allowed}</td>
                              <td>
                                <span
                                  className={
                                    row.points_allowed_rank <= 5
                                      ? "badge badge--good"
                                      : row.points_allowed_rank > row.teams_ranked - 5
                                        ? "badge badge--bad"
                                        : "badge"
                                  }
                                >
                                  {row.points_allowed_rank} of {row.teams_ranked}
                                </span>
                              </td>
                              <td className="num">{row.rebounds_allowed}</td>
                              <td className="num">{row.assists_allowed}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                      Averaged per opposing player-game rather than summed, so a team that has
                      simply played more games does not look like a worse defence. Rank 1 is the
                      stingiest in the league at that position.
                    </p>
                  </>
                )}
              </Async>
            </Panel>
          </Section>

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

          <Section
            title="Shot defense"
            note="Where opponents shoot against this team, and how well they do."
          >
            <Panel title="Where this team allows shots" tools={<ShotChartLegend />}>
              <div className="grid grid--2">
                <Async query={shotDefense} empty={(d) => d.cells.length === 0}>
                  {(shotData) => (
                    <ShotChart
                      cells={shotData.cells}
                      binSize={shotData.bin_size}
                      midpoint={shotData.points_per_attempt ?? 1}
                      minAttempts={2}
                    />
                  )}
                </Async>
                <Async query={shotDefense}>
                  {(shotData) => (
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Zone</th>
                            <th>Att</th>
                            <th>FG% allowed</th>
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
              <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                Blue is where opponents score <em>well</em> against this team — the defensive weak
                spots, not its strengths. shot_locations records who took a shot, so this resolves
                the opponent per game rather than filtering on team, and won&apos;t match the
                offensive chart above bin for bin.
              </p>
            </Panel>

            <Panel
              title="Who's gone off against this defense"
              hint="opposing shooters, ranked by points scored"
              flush
            >
              <Async query={shotDefense} empty={(d) => d.by_player.length === 0}>
                {(shotData) => (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Player</th>
                          <th>Team</th>
                          <th>G</th>
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
                            <td>{row.team_abbr ?? "—"}</td>
                            <td>{row.games}</td>
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
        </>
      )}
    </Async>
  );
}
