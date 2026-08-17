import { useMemo, useState } from "react";
import { Async, Panel, Section, SeasonPicker, TeamCell } from "../components/ui";
import type { TeamRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, rate, seasonOptions } from "../lib/format";

export default function Teams() {
  const [season, setSeason] = useState(CURRENT_SEASON);
  const seasons = useMemo(() => seasonOptions(), []);
  const teams = useQuery<{ teams: TeamRow[] }>(`/teams?season=${season}`);

  return (
    <Section title="Teams" note="Every franchise, ranked by record.">
      <Panel
        title={`${season} franchises`}
        tools={<SeasonPicker season={season} seasons={seasons} onChange={setSeason} />}
      >
        <Async query={teams} empty={(d) => d.teams.length === 0}>
          {(data) => (
            <div className="grid grid--3">
              {data.teams.map((team) => (
                <article key={team.id} className="panel" style={{ padding: "var(--s-4)" }}>
                  <TeamCell teamId={team.id} name={team.name} size="lg"
                    meta={team.conference ?? undefined} />
                  <div style={{ display: "flex", gap: "var(--s-4)", marginTop: "var(--s-3)" }}>
                    <span className="num" style={{ fontSize: "var(--t-lg)", fontWeight: 620 }}>
                      {team.wins ?? "—"}-{team.losses ?? "—"}
                    </span>
                    <span className="muted num" style={{ alignSelf: "center" }}>
                      {rate(team.win_percentage)}
                      {team.playoff_seed ? ` · #${team.playoff_seed} seed` : ""}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </Section>
  );
}
