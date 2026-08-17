import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Async, Panel, Section, SeasonPicker, TeamLogo } from "../components/ui";
import type { GameRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, longDate, seasonOptions, timeOf } from "../lib/format";

function GameRowLine({ game }: { game: GameRow }) {
  const final = game.status === "final";
  const homeWon = final && (game.home_score ?? 0) > (game.away_score ?? 0);

  return (
    <Link
      to={`/games/${game.id}`}
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: "var(--s-3)",
        padding: "var(--s-3) var(--s-4)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <span style={{ display: "grid", gap: "var(--s-1)" }}>
        {[
          { abbr: game.away_abbr, name: game.away_team, score: game.away_score, winner: final && !homeWon },
          { abbr: game.home_abbr, name: game.home_team, score: game.home_score, winner: homeWon },
        ].map((side) => (
          <span key={side.abbr} style={{ display: "flex", alignItems: "center", gap: "var(--s-2)" }}>
            <span style={{ fontWeight: side.winner ? 640 : 460, minWidth: 0 }}>{side.name}</span>
            <span
              className="num"
              style={{ marginLeft: "auto", fontWeight: side.winner ? 640 : 460 }}
            >
              {final ? side.score : ""}
            </span>
          </span>
        ))}
      </span>
      <span className="muted" style={{ fontSize: "var(--t-xs)", alignSelf: "center", textAlign: "right" }}>
        {final ? "Final" : timeOf(game.start_time)}
      </span>
    </Link>
  );
}

export default function Games() {
  const [season, setSeason] = useState(CURRENT_SEASON);
  const seasons = useMemo(() => seasonOptions(), []);
  const games = useQuery<{ games: GameRow[] }>(`/games?season=${season}&limit=120`);

  const byDate = useMemo(() => {
    const grouped = new Map<string, GameRow[]>();
    for (const game of games.data?.games ?? []) {
      const key = new Date(game.start_time).toDateString();
      grouped.set(key, [...(grouped.get(key) ?? []), game]);
    }
    return [...grouped.entries()];
  }, [games.data]);

  return (
    <Section title="Games" note="Most recent first.">
      <Panel
        title={`${season} schedule`}
        tools={<SeasonPicker season={season} seasons={seasons} onChange={setSeason} />}
        flush
      >
        <Async query={games} empty={(data) => data.games.length === 0}>
          {() => (
            <div>
              {byDate.map(([date, rows]) => (
                <div key={date}>
                  <h4
                    style={{
                      padding: "var(--s-2) var(--s-4)",
                      background: "var(--sunken)",
                      fontSize: "var(--t-xs)",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: "var(--ink-muted)",
                      fontWeight: 600,
                      position: "sticky",
                      top: "var(--nav-height)",
                    }}
                  >
                    {longDate(rows[0].start_time)}
                  </h4>
                  {rows.map((game) => (
                    <GameRowLine key={game.id} game={game} />
                  ))}
                </div>
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </Section>
  );
}

export { TeamLogo };
