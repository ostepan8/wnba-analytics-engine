/* "Who is this player playing next, and does it favour them?"
 *
 * Two questions, both answerable from data the site already has, just never
 * combined:
 *   1. How has this player actually done against this specific opponent,
 *      across every game they've played them (not just this season -- a
 *      season alone is often one or two meetings, too little to say anything).
 *   2. Do the zones this player scores well from overlap with the zones this
 *      opponent's defence is weak in? That's a season-long, volume-backed
 *      comparison on both sides, not a small-sample head-to-head one --
 *      shot_locations has far too few matchup-specific attempts per pair of
 *      teams to say anything about a single opponent's shot defence, so the
 *      defence side is that team's overall profile, same as the shot-defense
 *      chart elsewhere on the site.
 *
 * Deliberately not editorial beyond one badge: the table shows the actual
 * rates against league average so a reader can judge the size of the edge
 * themselves, the way the rest of this site's stats pages do.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Panel, Section, Skeleton, TeamLogo } from "./ui";
import type { GameLogRow, ScheduleRow, ShotChartResponse, ShotDefenseResponse, ShotZone, TeamRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { avg, pct, shortDate } from "../lib/format";
import { teamColor } from "../lib/teamColors";

/** Below this many attempts, a season-long zone rate is too noisy to call a
 *  strength or a weakness -- corner threes and backcourt heaves are the
 *  usual casualties, correctly. */
const ZONE_MIN_ATTEMPTS = 15;

/** Below this margin against league average, a "weakness" or "strength" is
 *  sampling noise wearing a verdict. An efficient player clears league
 *  average in nearly every zone by definition, so `> 0` alone would call
 *  almost the whole floor a "hot zone" against almost any opponent -- three
 *  points of separation is the bar for something worth pointing at. */
const EDGE_THRESHOLD = 0.03;

interface ZoneComparison {
  zone: string;
  playerRate: number;
  defenseRate: number;
  leagueRate: number;
  playerEdge: number;
  defenseWeak: number;
}

function zoneComparisons(
  playerZones: ShotZone[],
  opponentZones: ShotZone[],
  leagueZones: ShotZone[],
): ZoneComparison[] {
  const byZone = <T extends { zone: string }>(rows: T[]) => new Map(rows.map((row) => [row.zone, row]));
  const opponentByZone = byZone(opponentZones);
  const leagueByZone = byZone(leagueZones);

  const rows: ZoneComparison[] = [];
  for (const playerZone of playerZones) {
    const defense = opponentByZone.get(playerZone.zone);
    const league = leagueByZone.get(playerZone.zone);
    if (!defense || !league) continue;
    if (playerZone.attempts < ZONE_MIN_ATTEMPTS || defense.attempts < ZONE_MIN_ATTEMPTS) continue;

    const leagueRate = league.makes / league.attempts;
    const playerRate = playerZone.makes / playerZone.attempts;
    const defenseRate = defense.makes / defense.attempts;
    rows.push({
      zone: playerZone.zone,
      playerRate,
      defenseRate,
      leagueRate,
      playerEdge: playerRate - leagueRate,
      defenseWeak: defenseRate - leagueRate,
    });
  }
  // Biggest combined edge first -- where the player is hottest against the
  // defence that's weakest, together, rises to the top.
  return rows.sort((a, b) => b.playerEdge + b.defenseWeak - (a.playerEdge + a.defenseWeak));
}

export default function PlayerMatchup({
  playerTeamId,
  season,
  gameLog,
  playerZones,
}: {
  playerTeamId: number;
  season: number;
  gameLog: GameLogRow[];
  playerZones: ShotZone[];
}) {
  const teamSchedule = useQuery<{ schedule: ScheduleRow[] }>(`/teams/${playerTeamId}?season=${season}`);
  const teams = useQuery<{ teams: TeamRow[] }>(`/teams?season=${season}`);

  /* The nearest game that hasn't been played yet -- what "who do they play
     next" actually means. Off-season or end-of-schedule leaves nothing here,
     which is why the picker below can always override it by hand. */
  const nextGame = useMemo(() => {
    const upcoming = (teamSchedule.data?.schedule ?? [])
      .filter((game) => game.status !== "final")
      .sort((a, b) => a.start_time.localeCompare(b.start_time));
    return upcoming[0] ?? null;
  }, [teamSchedule.data]);

  const [manualOpponentId, setManualOpponentId] = useState<number | null>(null);
  const opponentId = manualOpponentId ?? nextGame?.opponent_id ?? null;
  const opponent = teams.data?.teams.find((team) => team.id === opponentId) ?? null;

  const opponentDefense = useQuery<ShotDefenseResponse>(
    opponentId ? `/teams/${opponentId}/defense?season=${season}` : null,
  );
  const leagueShots = useQuery<ShotChartResponse>(`/shots?season=${season}`);

  const vsOpponent = useMemo(() => {
    if (!opponentId) return null;
    const games = gameLog.filter((game) => game.opponent_id === opponentId && game.status === "final");
    if (!games.length) return { games: 0 as const };
    const sum = (pick: (game: GameLogRow) => number | null) =>
      games.reduce((total, game) => total + (pick(game) ?? 0), 0);
    const fgm = sum((game) => game.field_goals_made);
    const fga = sum((game) => game.field_goals_attempted);
    return {
      games: games.length,
      points: sum((game) => game.points) / games.length,
      rebounds: sum((game) => game.rebounds) / games.length,
      assists: sum((game) => game.assists) / games.length,
      fieldGoalPct: fga > 0 ? fgm / fga : null,
    };
  }, [gameLog, opponentId]);

  const hotspots = useMemo(() => {
    if (!opponentDefense.data || !leagueShots.data) return [];
    return zoneComparisons(playerZones, opponentDefense.data.zones, leagueShots.data.zones);
  }, [playerZones, opponentDefense.data, leagueShots.data]);

  return (
    <Section
      title="Next matchup"
      note="Career history against one opponent, and whether this player's own hot zones line up with that defence's soft spots."
    >
      <Panel
        accent={opponent ? teamColor(opponent.abbreviation) : undefined}
        tools={
          <select
            className="control"
            aria-label="Compare against a different team"
            value={opponentId ?? ""}
            onChange={(event) => setManualOpponentId(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">
              {nextGame ? `Next: ${nextGame.opponent_abbr}` : "Choose a team"}
            </option>
            {(teams.data?.teams ?? [])
              .filter((team) => team.id !== playerTeamId)
              .sort((a, b) => a.abbreviation.localeCompare(b.abbreviation))
              .map((team) => (
                <option key={team.id} value={team.id}>
                  {team.abbreviation}
                </option>
              ))}
          </select>
        }
      >
        {/* Loading is distinct from "no upcoming game" -- until teamSchedule
            resolves, opponentId is null for the same reason a real off-season
            would make it null, and the two must not look identical. */}
        {teamSchedule.loading && manualOpponentId === null ? (
          <Skeleton rows={4} />
        ) : !opponentId ? (
          <p className="empty">No upcoming game on the schedule — pick a team above to compare against.</p>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)", marginBottom: "var(--s-5)" }}>
              <TeamLogo teamId={opponentId} size="md" />
              <div>
                <Link to={`/teams/${opponentId}`} className="team-mark" style={{ color: teamColor(opponent?.abbreviation) }}>
                  {opponent?.abbreviation ?? "—"}
                </Link>
                <p className="muted" style={{ fontSize: "var(--t-xs)" }}>
                  {nextGame && nextGame.opponent_id === opponentId
                    ? `${nextGame.is_home ? "Home" : "Away"} · ${shortDate(nextGame.start_time)}`
                    : opponent?.name ?? "Not on the upcoming schedule"}
                </p>
              </div>
            </div>

            {vsOpponent && vsOpponent.games > 0 ? (
              <div className="grid grid--4" style={{ marginBottom: "var(--s-5)" }}>
                <div className="stat">
                  <span className="stat__value">{vsOpponent.games}</span>
                  <span className="stat__label">Career meetings</span>
                </div>
                <div className="stat">
                  <span className="stat__value">{avg(vsOpponent.points)}</span>
                  <span className="stat__label">PPG vs {opponent?.abbreviation}</span>
                </div>
                <div className="stat">
                  <span className="stat__value">{avg(vsOpponent.rebounds)}</span>
                  <span className="stat__label">RPG vs {opponent?.abbreviation}</span>
                </div>
                <div className="stat">
                  <span className="stat__value">{avg(vsOpponent.assists)}</span>
                  <span className="stat__label">APG vs {opponent?.abbreviation}</span>
                </div>
              </div>
            ) : (
              <p className="empty" style={{ padding: "0 0 var(--s-5)" }}>
                Never faced {opponent?.abbreviation ?? "this team"} — no career meetings recorded.
              </p>
            )}

            {opponentDefense.loading || leagueShots.loading ? (
              <Skeleton rows={4} />
            ) : hotspots.length === 0 ? (
                <p className="empty">
                  Not enough volume on both sides this season to call a zone a real strength or weakness yet.
                </p>
            ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th className="name">Zone</th>
                          <th>{opponent?.abbreviation} allows</th>
                          <th>League avg</th>
                          <th>Player shoots</th>
                          <th>Read</th>
                        </tr>
                      </thead>
                      <tbody>
                        {hotspots.map((row) => {
                          const attacking = row.playerEdge > EDGE_THRESHOLD && row.defenseWeak > EDGE_THRESHOLD;
                          const avoiding = row.playerEdge < -EDGE_THRESHOLD && row.defenseWeak < -EDGE_THRESHOLD;
                          return (
                            <tr key={row.zone}>
                              <td className="name">{row.zone}</td>
                              <td>{pct(row.defenseRate)}</td>
                              <td className="muted">{pct(row.leagueRate)}</td>
                              <td>{pct(row.playerRate)}</td>
                              <td>
                                {attacking && <span className="badge badge--good">hot zone</span>}
                                {avoiding && <span className="badge badge--bad">cold zone</span>}
                                {!attacking && !avoiding && <span className="muted">—</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                      "Hot zone" means this player clears league average from there by at least 3 points AND{" "}
                      {opponent?.abbreviation} allows at least 3 points more than league average from there —
                      both season-long rates, not this matchup's own (too few head-to-head shots to say anything
                      on their own).
                    </p>
                  </div>
            )}
          </>
        )}
      </Panel>
    </Section>
  );
}
