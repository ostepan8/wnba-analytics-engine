import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Async, Panel, Section, SeasonPicker, TeamLogo } from "../components/ui";
import type { ClosingLine, GameRow } from "../lib/api";
import { moneylineLabel, spreadLabel, useQuery } from "../lib/api";
import { CURRENT_SEASON, longDate, seasonOptions, shortDate, timeOf } from "../lib/format";
import { teamColor } from "../lib/teamColors";

/** One team's row inside a game: logo, name, score. A 3px tick in the
 *  winner's own colour is the only thing distinguishing a final from the
 *  120 identical-looking rows around it at a glance. */
function Side({
  teamId,
  abbr,
  name,
  score,
  winner,
  show,
}: {
  teamId: number | undefined;
  abbr: string;
  name: string;
  score: number | null;
  winner: boolean;
  show: boolean;
}) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "var(--s-3)", minWidth: 0 }}>
      <span
        aria-hidden="true"
        style={{
          width: 3,
          height: 18,
          borderRadius: 2,
          background: winner ? teamColor(abbr) : "transparent",
        }}
      />
      <TeamLogo teamId={teamId} size="sm" />
      <span
        style={{
          fontWeight: winner ? 640 : 460,
          flex: "1 1 auto",
          minWidth: 0,
          overflow: "hidden",
          whiteSpace: "nowrap",
          textOverflow: "ellipsis",
        }}
      >
        {name}
      </span>
      <span
        className="num"
        style={{
          marginLeft: "auto",
          fontFamily: "var(--t-display)",
          fontSize: "17px",
          fontWeight: winner ? 700 : 500,
          color: winner ? "var(--ink)" : "var(--ink-muted)",
        }}
      >
        {show ? score : ""}
      </span>
    </span>
  );
}

function GameRowLine({ game, line }: { game: GameRow; line?: ClosingLine }) {
  const final = game.status === "final";
  const homeWon = final && (game.home_score ?? 0) > (game.away_score ?? 0);

  return (
    <Link
      to={`/games/${game.id}`}
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) 132px 96px",
        gap: "var(--s-4)",
        padding: "var(--s-3) var(--s-4)",
        borderBottom: "1px solid var(--line)",
        alignItems: "center",
      }}
    >
      <span style={{ display: "grid", gap: "var(--s-2)", minWidth: 0 }}>
        <Side
          teamId={game.away_team_id}
          abbr={game.away_abbr}
          name={game.away_team}
          score={game.away_score}
          winner={final && !homeWon}
          show={final}
        />
        <Side
          teamId={game.home_team_id}
          abbr={game.home_abbr}
          name={game.home_team}
          score={game.home_score}
          winner={homeWon}
          show={final}
        />
        {game.season_type && game.season_type !== "regular-season" && (
          <span className="badge badge--warn" style={{ justifySelf: "start" }}>
            {game.season_type.replace("-", " ")}
          </span>
        )}
      </span>

      {/* The closing number. Absent is stated rather than left blank: a silent
          gap reads as a broken feature, and this one has a real cause. */}
      <span style={{ fontSize: "var(--t-xs)", lineHeight: 1.5 }}>
        {line ? (
          <>
            <span className="num">
              {game.home_abbr} {spreadLabel(line.spread_home)}
            </span>
            <br />
            <span className="num muted">O/U {line.total ?? "—"}</span>
            <br />
            <span className="num muted">
              {moneylineLabel(line.moneyline_away)} / {moneylineLabel(line.moneyline_home)}
            </span>
          </>
        ) : (
          <span className="muted">no line recorded</span>
        )}
      </span>

      <span style={{ fontSize: "var(--t-xs)", textAlign: "right", lineHeight: 1.6 }}>
        <span className="muted">{final ? "Final" : timeOf(game.start_time)}</span>
        {line?.home_covered != null && (
          <>
            <br />
            <span className={line.home_covered ? "badge badge--good" : "badge badge--bad"}>
              {line.home_covered ? game.home_abbr : game.away_abbr} cover
            </span>
          </>
        )}
        {line?.went_over != null && (
          <>
            <br />
            <span className="badge">{line.went_over ? "over" : "under"}</span>
          </>
        )}
      </span>
    </Link>
  );
}

export default function Games() {
  const [season, setSeason] = useState(CURRENT_SEASON);
  const [teamFilter, setTeamFilter] = useState<string>("all");
  const seasons = useMemo(() => seasonOptions(), []);
  const games = useQuery<{ games: GameRow[] }>(`/games?season=${season}&limit=120`);

  /* Lines are fetched in one batch for every game on screen rather than per
     row: 120 rows would otherwise be 120 requests for data one query returns. */
  const ids = (games.data?.games ?? []).map((game) => game.id).join(",");
  const lines = useQuery<{ lines: Record<string, ClosingLine> }>(
    ids ? `/lines/closing?game_ids=${ids}` : null,
  );

  /* Built from the games already on screen rather than a separate /teams
     call — every team playing this season necessarily appears in its own
     schedule, so a second round trip would only duplicate what is fetched
     already. */
  const teamOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const game of games.data?.games ?? []) {
      seen.set(game.home_team_id, game.home_abbr);
      seen.set(game.away_team_id, game.away_abbr);
    }
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [games.data]);

  const filtered = useMemo(() => {
    const rows = games.data?.games ?? [];
    if (teamFilter === "all") return rows;
    const id = Number(teamFilter);
    return rows.filter((game) => game.home_team_id === id || game.away_team_id === id);
  }, [games.data, teamFilter]);

  const byDate = useMemo(() => {
    const grouped = new Map<string, GameRow[]>();
    for (const game of filtered) {
      const key = new Date(game.start_time).toDateString();
      grouped.set(key, [...(grouped.get(key) ?? []), game]);
    }
    return [...grouped.entries()];
  }, [filtered]);

  /* Where the odds feed actually stops. Derived rather than hardcoded, so the
     note stops appearing on its own once the feed is restored — a fixed date in
     the copy would quietly become a lie. */
  const coverage = useMemo(() => {
    const rows = games.data?.games ?? [];
    const map = lines.data?.lines;
    if (!rows.length || !map) return null;
    const withLine = rows.filter((game) => map[String(game.id)]);
    if (!withLine.length || withLine.length === rows.length) return null;
    const newest = withLine.reduce((a, b) => (a.start_time > b.start_time ? a : b));
    return { newest: newest.start_time, missing: rows.length - withLine.length };
  }, [games.data, lines.data]);

  return (
    <Section title="Games" note="Most recent first.">
      <Panel
        title={`${season} schedule`}
        hint={
          coverage
            ? `Lines through ${shortDate(coverage.newest)} — ${coverage.missing} later games have none`
            : undefined
        }
        tools={
          <>
            <select
              className="control"
              aria-label="Filter by team"
              value={teamFilter}
              onChange={(event) => setTeamFilter(event.target.value)}
            >
              <option value="all">All teams</option>
              {teamOptions.map(([id, abbr]) => (
                <option key={id} value={id}>
                  {abbr}
                </option>
              ))}
            </select>
            <SeasonPicker season={season} seasons={seasons} onChange={setSeason} />
          </>
        }
        flush
      >
        <Async query={games} empty={(data) => data.games.length === 0}>
          {() =>
            byDate.length === 0 ? (
              <p className="empty">No games for the selected team this season.</p>
            ) : (
            <div>
              {byDate.map(([date, rows]) => (
                <div key={date}>
                  <h4
                    style={{
                      padding: "var(--s-2) var(--s-4)",
                      background: "var(--sunken)",
                      borderBottom: "1px solid var(--line)",
                      fontFamily: "var(--t-display)",
                      fontSize: "15px",
                      textTransform: "uppercase",
                      letterSpacing: "0.02em",
                      color: "var(--ink-2)",
                      fontWeight: 700,
                      position: "sticky",
                      top: "var(--nav-height)",
                      zIndex: 1,
                    }}
                  >
                    {longDate(rows[0].start_time)}
                  </h4>
                  {rows.map((game) => (
                    <GameRowLine
                      key={game.id}
                      game={game}
                      line={lines.data?.lines?.[String(game.id)]}
                    />
                  ))}
                </div>
              ))}
            </div>
            )
          }
        </Async>
      </Panel>
    </Section>
  );
}
