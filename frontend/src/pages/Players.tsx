import { useCallback, useEffect, useMemo, useState } from "react";
import { Async, Panel, PlayerCell, Section, SeasonPicker, SortTh } from "../components/ui";
import type { PlayerRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, avg, seasonOptions } from "../lib/format";
import { useSort } from "../lib/useSort";

type SortColumn = "games_played" | "minutes" | "points";

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

  // Hooks can't live inside Async's render-prop children -- it only calls
  // that function once data exists, so a hook there would fire on some
  // renders and not others. Sorting the (possibly still-undefined) row list
  // up here keeps the hook order stable across loading, error and loaded.
  const accessor = useCallback((row: PlayerRow, key: SortColumn) => row[key], []);
  const { sorted, sortKey, direction, toggleSort } = useSort<PlayerRow, SortColumn>(
    players.data?.players ?? [],
    accessor,
    "points",
  );

  return (
    <Section
      title="Players"
      note="Everyone who appeared this season, ranked by scoring — click a column to sort by it instead."
    >
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
          {() => (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Team</th>
                    <th>Pos</th>
                    <SortTh
                      label="G"
                      column="games_played"
                      active={sortKey === "games_played"}
                      direction={direction}
                      onSort={toggleSort}
                    />
                    <SortTh
                      label="MIN"
                      column="minutes"
                      active={sortKey === "minutes"}
                      direction={direction}
                      onSort={toggleSort}
                    />
                    <SortTh
                      label="PTS"
                      column="points"
                      active={sortKey === "points"}
                      direction={direction}
                      onSort={toggleSort}
                    />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((player) => (
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
