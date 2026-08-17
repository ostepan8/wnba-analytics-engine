import { useEffect, useMemo, useState } from "react";
import GamePanel from "../components/GamePanel";
import SlateBar from "../components/SlateBar";
import SlateTrends from "../components/SlateTrends";
import { Async, Panel, Section } from "../components/ui";
import type { ClosingLine, GameRow, SlateResponse } from "../lib/api";
import { useQuery } from "../lib/api";
import { CURRENT_SEASON, longDate } from "../lib/format";

/**
 * The scoreboard, one day at a time.
 *
 * It opens on the most recent day that HAS games rather than on today's date.
 * Today is frequently empty — an off day, or the off-season — and an empty
 * scoreboard is indistinguishable from a broken one.
 *
 * One /slate call carries the context for the whole day: every team's record,
 * form, rest and injury report, plus the props whose live price and recent
 * frequency disagree most. Per-game that would be a dozen round trips repeating
 * the same player-history query to render one screen.
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
  const canGoEarlier = index < days.length - 1;
  const canGoLater = index > 0;

  // Left/right steps a day at a time, matching the Earlier/Later buttons.
  // Ignored while a form control has focus so it never fights a select or
  // text field's own use of the arrow keys.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.key === "ArrowLeft" && canGoEarlier) {
        setOffset((value) => value + 1);
      } else if (event.key === "ArrowRight" && canGoLater) {
        setOffset((value) => value - 1);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canGoEarlier, canGoLater]);

  const ids = (current?.[1] ?? []).map((game) => game.id).join(",");
  const lines = useQuery<{ lines: Record<string, ClosingLine> }>(
    ids ? `/lines/closing?game_ids=${ids}` : null,
  );
  const slate = useQuery<SlateResponse>(ids ? `/slate?game_ids=${ids}` : null);

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
              disabled={!canGoEarlier}
              title="Earlier day (left arrow)"
              aria-label="Show the earlier day's games (left arrow key)"
            >
              ‹ Earlier
            </button>
            <button
              className="control"
              onClick={() => setOffset((value) => value - 1)}
              disabled={!canGoLater}
              title="Later day (right arrow)"
              aria-label="Show the later day's games (right arrow key)"
            >
              Later ›
            </button>
          </>
        }
        flush
      >
        <Async query={games} empty={() => days.length === 0}>
          {() => (
            <>
              {slate.data && <SlateBar slate={slate.data} />}
              <div style={{ display: "grid", gap: "var(--s-3)", padding: "var(--s-3)" }}>
                {(current?.[1] ?? []).map((game) => (
                  <GamePanel
                    key={game.id}
                    game={game}
                    line={lines.data?.lines?.[String(game.id)]}
                    season={CURRENT_SEASON}
                    context={slate.data?.teams}
                  />
                ))}
              </div>
            </>
          )}
        </Async>
      </Panel>

      {/* Below the games rather than above them: the scoreboard is what the
          page is for, and this is a way into it, not a replacement. */}
      <Panel
        title="Where the market and the record disagree"
        hint="across every game on this slate"
      >
        <Async query={slate}>
          {(data) => (
            <SlateTrends
              trends={data.trends}
              balance={data.balance}
              ruledOut={data.totals.props_ruled_out}
            />
          )}
        </Async>
      </Panel>
    </Section>
  );
}
