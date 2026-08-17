/* Both sides of a game, side by side: record, form, scoring, rest, betting
 * record and who is out.
 *
 * "Team lines" was a closing number and two movement charts, which tells you
 * what the market thinks and nothing about why. This is the context that makes
 * the number readable — a team on three days' rest averaging 89 against a team
 * allowing 77 is the actual content of a spread.
 *
 * Everything is cut at tip-off, so a completed game shows what was known
 * beforehand rather than a record containing its own result.
 */

import { Link } from "react-router-dom";
import Absences from "./Absences";
import DefenseBars from "../charts/DefenseBars";
import { Async, TeamLogo } from "./ui";
import type { MatchupResponse, MatchupSide } from "../lib/api";
import { useQuery } from "../lib/api";
import { pct } from "../lib/format";
import { badgeClass, injuryDetail, isOut, statusRank } from "../lib/injury";

function Row({ label, home, away }: { label: string; home: string; away: string }) {
  return (
    <tr>
      <td className="num">{away}</td>
      <td
        style={{
          textAlign: "center",
          fontSize: "var(--t-xs)",
          color: "var(--ink-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </td>
      <td className="num" style={{ textAlign: "left" }}>
        {home}
      </td>
    </tr>
  );
}

function record(side: MatchupSide) {
  const form = side.form;
  if (!form || form.games == null) return "—";
  return `${form.wins}-${form.losses}`;
}

function ats(side: MatchupSide) {
  const b = side.betting;
  if (!b || b.covers + b.non_covers === 0) return "—";
  return `${b.covers}-${b.non_covers} (${pct(b.covers / (b.covers + b.non_covers), 0)})`;
}

function overUnder(side: MatchupSide) {
  const b = side.betting;
  if (!b || b.overs + b.unders === 0) return "—";
  return `${b.overs}-${b.unders} (${pct(b.overs / (b.overs + b.unders), 0)})`;
}

function lastTen(side: MatchupSide) {
  const f = side.form;
  if (!f || !f.games_l10 || f.wins_l10 == null) return "—";
  return `${f.wins_l10}-${f.games_l10 - f.wins_l10}`;
}

function Injuries({ side, label }: { side: MatchupSide; label: string }) {
  // Most severe first, so the name that changes a lineup is the one read first.
  const listed = [...side.injuries].sort(
    (a, b) => statusRank(a.status) - statusRank(b.status),
  );
  return (
    <div>
      <h5 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
        {label}
      </h5>
      {side.injuries.length === 0 ? (
        <p className="muted" style={{ fontSize: "var(--t-sm)" }}>
          Nobody listed.
        </p>
      ) : (
        <ul style={{ display: "grid", gap: "var(--s-1)" }}>
          {listed.map((row) => (
            <li
              key={row.player_id}
              style={{ display: "flex", gap: "var(--s-2)", fontSize: "var(--t-sm)" }}
            >
              <span className={badgeClass(row.status)} style={{ flex: "none" }}>
                {row.status}
              </span>
              <Link to={`/players/${row.player_id}`}>{row.full_name}</Link>
              <span className="muted" style={{ fontSize: "var(--t-xs)", alignSelf: "center" }}>
                {injuryDetail(row)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Matchup({
  gameId,
  homeAbbr,
  awayAbbr,
  homeTeamId,
  awayTeamId,
}: {
  gameId: number;
  homeAbbr: string;
  awayAbbr: string;
  homeTeamId: number;
  awayTeamId: number;
}) {
  const query = useQuery<MatchupResponse>(`/games/${gameId}/matchup`);

  return (
    <Async query={query}>
      {(data) => (
        <>
          <div className="table-wrap">
            <table className="table" style={{ tableLayout: "fixed" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "right" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--s-2)" }}>
                      <TeamLogo teamId={awayTeamId} size="sm" />
                      {awayAbbr}
                    </span>
                  </th>
                  <th style={{ textAlign: "center" }} />
                  <th style={{ textAlign: "left" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--s-2)" }}>
                      <TeamLogo teamId={homeTeamId} size="sm" />
                      {homeAbbr}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <Row label="Record" away={record(data.away)} home={record(data.home)} />
                <Row label="Last 10" away={lastTen(data.away)} home={lastTen(data.home)} />
                <Row
                  label="Points for"
                  away={String(data.away.form?.points_for ?? "—")}
                  home={String(data.home.form?.points_for ?? "—")}
                />
                <Row
                  label="Points against"
                  away={String(data.away.form?.points_against ?? "—")}
                  home={String(data.home.form?.points_against ?? "—")}
                />
                <Row
                  label="PF last 5"
                  away={String(data.away.form?.points_for_l5 ?? "—")}
                  home={String(data.home.form?.points_for_l5 ?? "—")}
                />
                <Row
                  label="PA last 5"
                  away={String(data.away.form?.points_against_l5 ?? "—")}
                  home={String(data.home.form?.points_against_l5 ?? "—")}
                />
                <Row
                  label="Rest"
                  away={data.away.rest_days == null ? "—" : `${data.away.rest_days}d`}
                  home={data.home.rest_days == null ? "—" : `${data.home.rest_days}d`}
                />
                <Row label="ATS" away={ats(data.away)} home={ats(data.home)} />
                <Row label="Over / under" away={overUnder(data.away)} home={overUnder(data.home)} />
                <Row
                  label="Out"
                  away={String(data.away.injuries.filter((r) => isOut(r.status)).length)}
                  home={String(data.home.injuries.filter((r) => isOut(r.status)).length)}
                />
              </tbody>
            </table>
          </div>

          <div className="grid grid--2" style={{ marginTop: "var(--s-4)" }}>
            {data.away.absences ? (
              <Absences side={data.away} label={`${awayAbbr} availability`} />
            ) : (
              <Injuries side={data.away} label={`${awayAbbr} injury report`} />
            )}
            {data.home.absences ? (
              <Absences side={data.home} label={`${homeAbbr} availability`} />
            ) : (
              <Injuries side={data.home} label={`${homeAbbr} injury report`} />
            )}
          </div>

          {(data.away.defense?.length || data.home.defense?.length) && (
            <div style={{ marginTop: "var(--s-5)" }}>
              <h5 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
                What each defence gives up
              </h5>
              <DefenseBars
                away={{ abbr: awayAbbr, rows: data.away.defense ?? [] }}
                home={{ abbr: homeAbbr, rows: data.home.defense ?? [] }}
              />
            </div>
          )}

          <p className="prose" style={{ marginTop: "var(--s-3)" }}>
            Records, scoring and rest are as of tip-off, so a finished game is shown with what was
            known before it rather than a record containing its own result. ATS and over/under are
            against the closing consensus with pushes excluded. Minutes and points beside a listed
            player are her season averages — what her absence removes, not a projection of what the
            team will now score. Defence is per opposing player-game across the season; rank 1 is
            the stingiest in the league.
          </p>
        </>
      )}
    </Async>
  );
}
