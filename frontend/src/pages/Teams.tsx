import { Fragment, useMemo, useState } from "react";
import { Async, Panel, RaceBadge, Section, SeasonPicker, TeamCell, TeamLogo } from "../components/ui";
import type { StandingsResponse } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, rate, seasonOptions } from "../lib/format";

function StandingsTable({ data }: { data: StandingsResponse }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 34 }}>#</th>
            <th className="name">Team</th>
            <th>W</th>
            <th>L</th>
            <th>PCT</th>
            <th title="Games behind the league leader">GB</th>
            <th title="Games behind the last playoff place">GB8</th>
            <th>L10</th>
            <th>Home</th>
            <th>Away</th>
            <th>Conf</th>
            <th>Left</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {data.standings.map((row, index) => {
            // The cut line is the point of this table, so it is drawn rather
            // than left for the reader to count to.
            const isCut = index === data.playoff_spots;
            return (
              <Fragment key={row.team_id}>
                {isCut && (
                  <tr aria-hidden>
                    <td
                      colSpan={13}
                      style={{
                        padding: "var(--s-1) var(--s-3)",
                        background: "var(--sunken)",
                        borderTop: "2px solid var(--line-strong)",
                        fontSize: "var(--t-xs)",
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        color: "var(--ink-muted)",
                        textAlign: "left",
                      }}
                    >
                      Playoff cut — top {data.playoff_spots} qualify
                    </td>
                  </tr>
                )}
                <tr style={{ opacity: row.eliminated ? 0.72 : 1 }}>
                  <td className="num muted">{row.seed}</td>
                  <td className="name">
                    <TeamCell
                      teamId={row.team_id}
                      name={row.name}
                      meta={
                        row.conference
                          ? `${row.conference.replace(" Conference", "")}${
                              row.conference_seed ? ` #${row.conference_seed}` : ""
                            }`
                          : undefined
                      }
                    />
                  </td>
                  <td>{row.wins ?? "—"}</td>
                  <td>{row.losses ?? "—"}</td>
                  <td>{rate(row.win_percentage)}</td>
                  <td className="num">
                    {row.games_behind_leader === 0 ? "—" : row.games_behind_leader}
                  </td>
                  <td className="num">
                    {row.in_playoff_position ? "—" : row.games_behind_playoff}
                  </td>
                  <td className="num">
                    {row.last10_wins}-{row.last10_losses}
                  </td>
                  <td>{row.home_record ?? "—"}</td>
                  <td>{row.away_record ?? "—"}</td>
                  <td>{row.conference_record ?? "—"}</td>
                  <td className="num">{row.games_remaining}</td>
                  <td>
                    <RaceBadge status={row} />
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Teams() {
  const [season, setSeason] = useState(CURRENT_SEASON);
  const seasons = useMemo(() => seasonOptions(), []);
  const standings = useQuery<StandingsResponse>(`/standings?season=${season}`);

  return (
    <>
      <Section
        title="Playoff picture"
        note="Top eight records league-wide, not by conference."
      >
        <Panel
          title={`${season} standings`}
          hint={standings.data?.race_open ? "Race open" : "Field decided"}
          tools={<SeasonPicker season={season} seasons={seasons} onChange={setSeason} />}
          flush
        >
          <Async query={standings} empty={(data) => data.standings.length === 0}>
            {(data) => <StandingsTable data={data} />}
          </Async>
        </Panel>
        <p className="prose" style={{ marginTop: "var(--s-3)" }}>
          The WNBA has seeded its postseason league-wide since 2016 — the eight best records
          qualify regardless of conference, so a team can lead its conference and miss. The
          conference ranking under each team name is context, not a berth.
        </p>
        <p className="prose" style={{ marginTop: "var(--s-2)" }}>
          <strong>The status column is arithmetic, not position.</strong> “Eliminated” means a
          team cannot reach a top-eight finish even winning out — never merely that it sits below
          the line. A team ninth with games in hand reads “still alive”, and one holding eighth
          without being safe reads “in position”. Both sides of the cut can be undecided at once.
          Clinching is computed from wins and games remaining and stays conservative: tiebreakers
          are not modelled, so a team is only called settled when no tiebreak could change it.
        </p>
      </Section>

      <Section title="All teams">
        <Async query={standings} empty={(data) => data.standings.length === 0}>
          {(data) => (
            <div className="grid grid--3">
              {data.standings.map((row) => (
                <article key={row.team_id} className="panel" style={{ padding: "var(--s-4)" }}>
                  <div style={{ display: "flex", gap: "var(--s-3)", alignItems: "center" }}>
                    <TeamLogo teamId={row.team_id} size="lg" />
                    <div style={{ minWidth: 0 }}>
                      <TeamCell teamId={row.team_id} name={row.name} />
                      <div
                        style={{
                          display: "flex",
                          gap: "var(--s-3)",
                          alignItems: "baseline",
                          marginTop: "var(--s-1)",
                        }}
                      >
                        <span
                          className="num"
                          style={{ fontSize: "var(--t-lg)", fontWeight: 620 }}
                        >
                          {row.wins ?? "—"}-{row.losses ?? "—"}
                        </span>
                        <span className="muted num" style={{ fontSize: "var(--t-xs)" }}>
                          {rate(row.win_percentage)} · #{row.seed}
                        </span>
                      </div>
                      <div style={{ marginTop: "var(--s-2)" }}>
                        <RaceBadge status={row} />
                      </div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </Async>
      </Section>
    </>
  );
}
