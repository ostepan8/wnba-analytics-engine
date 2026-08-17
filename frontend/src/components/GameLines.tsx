/* Spread and total movement for one game, plus how it settled.
 *
 * Spread and total are two measures on different scales, so they get two charts
 * rather than two y-axes on one. A dual-axis chart lets the author choose where
 * the lines cross, which is the same as choosing the conclusion.
 *
 * Books are averaged per timestamp into a consensus. The individual quotes are
 * in the response for anyone who wants the disagreement, which is the subject
 * of the divergence work rather than of this chart.
 */

import { useMemo } from "react";
import { Async, Panel, Stat } from "./ui";
import type { ClosingLine, LineMovementRow } from "../lib/api";
import { moneylineLabel, spreadLabel, useQuery } from "../lib/api";
import { TimeSeries, type Series } from "../charts/primitives";

/**
 * Consensus over time, with each book's last quote carried forward.
 *
 * Averaging whatever happened to be captured in each time bucket looks obvious
 * and is wrong: books quote at different moments, so the set of books in a
 * bucket changes constantly and the "consensus" jumps every time a book with a
 * different number enters or leaves it. The result is a violent sawtooth that
 * is entirely an artefact of capture timing -- it reads as a line moving two
 * points and back, forty times, during a game where nothing moved.
 *
 * Carrying each vendor's most recent quote forward keeps the average over a
 * STABLE set of books, so a change in the line is a change in the line.
 */
function consensusSeries(
  rows: LineMovementRow[],
  field: "spread_home_value" | "total_value",
): { t: number; v: number }[] {
  const quotes = rows
    .filter((row) => row[field] != null)
    .map((row) => ({
      vendor: row.vendor,
      t: new Date(row.captured_at).getTime(),
      v: Number(row[field]),
    }))
    .sort((a, b) => a.t - b.t);
  if (!quotes.length) return [];

  const latest = new Map<string, number>();
  const out: { t: number; v: number }[] = [];
  let previous: number | null = null;

  for (const quote of quotes) {
    latest.set(quote.vendor, quote.v);
    const values = [...latest.values()];
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    // Only emit when the consensus actually changes; a flat line needs two
    // points, not four hundred.
    if (previous === null || Math.abs(mean - previous) > 1e-9) {
      out.push({ t: quote.t, v: mean });
      previous = mean;
    }
  }
  // Anchor the end so the series spans the full observed window.
  const last = quotes[quotes.length - 1];
  if (out.length && out[out.length - 1].t !== last.t && previous !== null) {
    out.push({ t: last.t, v: previous });
  }
  return out;
}

export default function GameLines({
  gameId,
  homeAbbr,
  awayAbbr,
}: {
  gameId: number;
  homeAbbr: string;
  awayAbbr: string;
}) {
  const movement = useQuery<{ movement: LineMovementRow[] }>(`/games/${gameId}/lines?limit=500`);
  const closing = useQuery<{ lines: Record<string, ClosingLine> }>(
    `/lines/closing?game_ids=${gameId}`,
  );

  const rows = movement.data?.movement ?? [];
  const spread = useMemo(() => consensusSeries(rows, "spread_home_value"), [rows]);
  const total = useMemo(() => consensusSeries(rows, "total_value"), [rows]);
  const books = useMemo(() => new Set(rows.map((row) => row.vendor)).size, [rows]);

  const line = closing.data?.lines?.[String(gameId)];

  const spreadSeries: Series[] = [
    { key: "spread", label: `${homeAbbr} spread`, color: "var(--series-1)", points: spread },
  ];
  const totalSeries: Series[] = [
    { key: "total", label: "Total", color: "var(--series-2)", points: total },
  ];

  const spreadDomain = spread.length
    ? ([
        Math.min(...spread.map((p) => p.v)) - 1,
        Math.max(...spread.map((p) => p.v)) + 1,
      ] as [number, number])
    : ([-10, 10] as [number, number]);
  const totalDomain = total.length
    ? ([Math.min(...total.map((p) => p.v)) - 2, Math.max(...total.map((p) => p.v)) + 2] as [
        number,
        number,
      ])
    : ([150, 180] as [number, number]);

  return (
    <>
      <Panel title="Closing line" hint={books ? `${books} books` : undefined}>
        {!closing.loading && !closing.error && !line && (
          <p className="empty">
            No sportsbook line recorded for this game.
            <br />
            <span style={{ fontSize: "var(--t-xs)" }}>
              The odds feed stopped on 2026-08-10 when its API key lapsed; history back to 2022
              is complete.
            </span>
          </p>
        )}
        <Async query={closing} empty={() => !line}>
          {() => (
            <div className="grid grid--4">
              <Stat
                value={spreadLabel(line!.spread_home)}
                label={`${homeAbbr} spread`}
                detail={
                  line!.home_covered === null
                    ? undefined
                    : line!.home_covered
                      ? `${homeAbbr} covered`
                      : `${awayAbbr} covered`
                }
              />
              <Stat
                value={line!.total ?? "—"}
                label="Total"
                detail={
                  line!.went_over === null
                    ? undefined
                    : line!.went_over
                      ? "went over"
                      : "went under"
                }
              />
              <Stat
                value={`${moneylineLabel(line!.moneyline_away)} / ${moneylineLabel(line!.moneyline_home)}`}
                label={`${awayAbbr} / ${homeAbbr} moneyline`}
              />
              <Stat value={String(line!.books)} label="Books at close" />
            </div>
          )}
        </Async>
      </Panel>

      <div className="grid grid--2">
        <Panel title={`${homeAbbr} spread movement`}>
          <Async query={movement} empty={() => spread.length < 2}>
            {() => (
              <TimeSeries
                series={spreadSeries}
                domain={spreadDomain}
                height={200}
                formatValue={(value) => (value > 0 ? `+${value.toFixed(1)}` : value.toFixed(1))}
                formatTime={(time) => new Date(time).toLocaleString()}
              />
            )}
          </Async>
        </Panel>

        <Panel title="Total movement">
          <Async query={movement} empty={() => total.length < 2}>
            {() => (
              <TimeSeries
                series={totalSeries}
                domain={totalDomain}
                height={200}
                formatValue={(value) => value.toFixed(1)}
                formatTime={(time) => new Date(time).toLocaleString()}
              />
            )}
          </Async>
        </Panel>
      </div>
    </>
  );
}
