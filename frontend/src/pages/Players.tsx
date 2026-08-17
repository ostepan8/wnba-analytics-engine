import { useEffect, useMemo, useState } from "react";
import { Async, Panel, PlayerCell, Section, SeasonPicker } from "../components/ui";
import type { PlayerRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, avg, seasonOptions } from "../lib/format";

/** Debounced so typing a name does not fire a request per keystroke. */
function useDebounced<T>(value: T, delay = 250) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

export default function Players() {
  const [season, setSeason] = useState(CURRENT_SEASON);
  const [search, setSearch] = useState("");
  const seasons = useMemo(() => seasonOptions(), []);
  const query = useDebounced(search.trim());

  const players = useQuery<{ players: PlayerRow[]; count: number }>(
    `/players?season=${season}&limit=400${query ? `&q=${encodeURIComponent(query)}` : ""}`,
  );

  return (
    <Section title="Players" note="Everyone who appeared this season, ranked by scoring.">
      <Panel
        title={query ? `Matching “${query}”` : `${season} players`}
        tools={
          <>
            <input
              className="input"
              style={{ width: 200 }}
              type="search"
              placeholder="Search by name"
              value={search}
              aria-label="Search players by name"
              onChange={(event) => setSearch(event.target.value)}
            />
            <SeasonPicker season={season} seasons={seasons} onChange={setSeason} />
          </>
        }
        flush
      >
        <Async query={players} empty={(data) => data.players.length === 0}>
          {(data) => (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Team</th>
                    <th>Pos</th>
                    <th>G</th>
                    <th>MIN</th>
                    <th>PTS</th>
                  </tr>
                </thead>
                <tbody>
                  {data.players.map((player) => (
                    <tr key={player.player_id}>
                      <td>
                        <PlayerCell playerId={player.player_id} name={player.full_name} />
                      </td>
                      <td>{player.team_abbr ?? "—"}</td>
                      <td>{player.position ?? "—"}</td>
                      <td>{player.games_played}</td>
                      <td>{avg(player.minutes)}</td>
                      <td>{avg(player.points)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>
    </Section>
  );
}
