import { useMemo, useState } from "react";
import GamePanel from "../components/GamePanel";
import { Async, Panel, Section } from "../components/ui";
import type { ClosingLine, GameRow } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, longDate } from "../lib/format";

/**
 * The scoreboard, one day at a time.
 *
 * It opens on the most recent day that HAS games rather than on today's date.
 * Today is frequently empty — an off day, or the off-season — and an empty
 * scoreboard is indistinguishable from a broken one.
 */
export default function Home() {
  const [offset, setOffset] = useState(0);
  const games = useQuery<{ games: GameRow[] }>(`/games?season=${CURRENT_SEASON}&limit=200`);

  /* Group into days, newest first, so stepping is over days that exist rather
     than over calendar dates that may hold nothing. */
  const days = useMemo(() => {
    const grouped = new Map<string, GameRow[]>();
    for (const game of games.data?.games ?? []) {
      const key = new Date(game.start_time).toDateString();
      grouped.set(key, [...(grouped.get(key) ?? []), game]);
    }
    return [...grouped.entries()];
  }, [games.data]);

  /* Open on TODAY when today has games, otherwise on the nearest day that does.
     Nearest by absolute distance, not "most recent": on a Tuesday with no games
     but a Wednesday slate, the next day is what someone wants, and previously
     this always fell back to the past. */
  const defaultIndex = useMemo(() => {
    if (!days.length) return 0;
    const today = new Date().toDateString();
    const exact = days.findIndex(([key]) => key === today);
    if (exact >= 0) return exact;

    const now = Date.now();
    let best = 0;
    let bestDistance = Infinity;
    days.forEach(([key], index) => {
      const distance = Math.abs(new Date(key).getTime() - now);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    });
    return best;
  }, [days]);

  const index = Math.min(Math.max(defaultIndex + offset, 0), Math.max(days.length - 1, 0));
  const current = days[index];

  const ids = (current?.[1] ?? []).map((game) => game.id).join(",");
  const lines = useQuery<{ lines: Record<string, ClosingLine> }>(
    ids ? `/lines/closing?game_ids=${ids}` : null,
  );

  return (
    <Section
      title="Scoreboard"
      note="Open a game for lines, props, shot charts, defense and the box score."
    >
      <Panel
        title={current ? longDate(current[1][0].start_time) : "No games"}
        hint={
          current
            ? `${current[1].length} game${current[1].length === 1 ? "" : "s"}` +
              (current[0] === new Date().toDateString() ? " · today" : "")
            : undefined
        }
        tools={
          <>
            <button
              className="control"
              onClick={() => setOffset((value) => value + 1)}
              disabled={index >= days.length - 1}
              title="Earlier day"
            >
              ‹ Earlier
            </button>
            <button
              className="control"
              onClick={() => setOffset((value) => value - 1)}
              disabled={index <= 0}
              title="Later day"
            >
              Later ›
            </button>
          </>
        }
        flush
      >
        <Async query={games} empty={() => days.length === 0}>
          {() => (
            <div style={{ display: "grid", gap: "var(--s-3)", padding: "var(--s-3)" }}>
              {(current?.[1] ?? []).map((game) => (
                <GamePanel
                  key={game.id}
                  game={game}
                  line={lines.data?.lines?.[String(game.id)]}
                  season={CURRENT_SEASON}
                />
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </Section>
  );
}
