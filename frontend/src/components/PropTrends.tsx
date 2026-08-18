/* Live prop lines with how often each has actually been cleared.
 *
 * The research view: the market says "over 24.5"; these columns say how often
 * this player has gone past 24.5 in her last five, ten and twenty games,
 * against this opponent, home and away.
 *
 * Two things are deliberate and load-bearing.
 *
 * A rate never appears without its denominator. "80%" and "4 of 5" are the same
 * arithmetic and different claims, and at these sample sizes the second is the
 * honest one — so the count is the primary text and the percentage is secondary.
 * Under four decided games the API returns no rate at all and the cell shows
 * only the count.
 *
 * Nothing here is a recommendation. A hit rate is the past frequency of an
 * outcome; this project's own findings record that no forecasting edge has been
 * produced from this data, and that blanket prop strategies lose once graded at
 * takeable prices.
 */

import { useMemo, useState } from "react";
import { Async, PlayerCell } from "./ui";
import type { PropTrendRow, TrendWindow } from "../lib/api";
import { propLabel, useQuery } from "../lib/api";
import { pct } from "../lib/format";

const COLUMNS = ["L5", "L10", "L20", "Season", "vs opp", "Home", "Away"];

function windowOf(row: PropTrendRow, label: string): TrendWindow | undefined {
  return row.windows.find((entry) => entry.label === label);
}

/** Count first, rate second — and no rate at all when the sample is too thin. */
function WindowCell({ window }: { window?: TrendWindow }) {
  if (!window || window.games === 0) return <span className="muted">—</span>;
  const decided = window.overs + window.unders;
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", lineHeight: 1.25 }}>
      <span className="num">
        {window.overs}/{decided || window.games}
      </span>
      {window.rate !== null && (
        <span
          className="num"
          style={{
            fontSize: "var(--t-xs)",
            color:
              window.rate >= 0.6
                ? "var(--good)"
                : window.rate <= 0.4
                  ? "var(--critical)"
                  : "var(--ink-muted)",
          }}
        >
          {Math.round(window.rate * 100)}%
        </span>
      )}
    </span>
  );
}

/** The last ten results as marks, oldest left. Shape and position carry the
    reading as much as colour: over sits high, under sits low. */
function RecentRun({ row }: { row: PropTrendRow }) {
  const recent = [...row.recent].slice(0, 10).reverse();
  if (!recent.length) return <span className="muted">—</span>;
  const width = recent.length * 11;
  return (
    <svg width={width} height={20} role="img" aria-label="Recent results against this line">
      {recent.map((game, index) => {
        const over = game.cleared === "over";
        const push = game.cleared === "push";
        return (
          <rect
            key={game.game_id}
            x={index * 11}
            y={push ? 7 : over ? 2 : 11}
            width={8}
            height={push ? 6 : 7}
            rx={2}
            fill={push ? "var(--ink-muted)" : over ? "var(--div-high)" : "var(--div-low)"}
          >
            <title>
              {game.value} · {game.cleared}
            </title>
          </rect>
        );
      })}
    </svg>
  );
}

export default function PropTrends({ gameId }: { gameId: number }) {
  const query = useQuery<{ props: PropTrendRow[] }>(`/games/${gameId}/trends`);
  const [market, setMarket] = useState<string>("all");

  const markets = useMemo(() => {
    const seen = new Set((query.data?.props ?? []).map((row) => row.prop_type));
    return ["all", ...[...seen].sort()];
  }, [query.data]);

  const rows = useMemo(() => {
    const all = query.data?.props ?? [];
    const filtered = market === "all" ? all : all.filter((row) => row.prop_type === market);
    // Strongest recent form first — that is what a reader scans for.
    return [...filtered].sort((a, b) => {
      const rate = (row: PropTrendRow) => windowOf(row, "L10")?.rate ?? -1;
      return rate(b) - rate(a);
    });
  }, [query.data, market]);

  return (
    <Async query={query} empty={(data) => data.props.length === 0}>
      {() => (
        <>
          <div style={{ display: "flex", gap: "var(--s-2)", marginBottom: "var(--s-3)", flexWrap: "wrap" }}>
            {markets.map((entry) => (
              <button
                key={entry}
                className="control"
                aria-pressed={market === entry}
                onClick={() => setMarket(entry)}
                style={{ height: 26, fontSize: "var(--t-xs)" }}
              >
                {entry === "all" ? "All markets" : propLabel(entry)}
              </button>
            ))}
          </div>

          <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th className="name">Player</th>
                  <th>Market</th>
                  <th>Line</th>
                  <th title="The market's implied probability of going over">Mkt</th>
                  <th>Venue</th>
                  {COLUMNS.map((label) => (
                    <th key={label}>{label}</th>
                  ))}
                  <th className="name">Last 10</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.provider}-${row.player_id}-${row.prop_type}-${row.line}`}>
                    <td className="name">
                      <PlayerCell playerId={row.player_id} name={row.full_name} />
                    </td>
                    <td>{propLabel(row.prop_type)}</td>
                    <td className="num">o{row.line}</td>
                    <td className="num muted">{pct(Number(row.over_probability), 0)}</td>
                    <td className="muted">{row.provider}</td>
                    {COLUMNS.map((label) => (
                      <td key={label}>
                        <WindowCell window={windowOf(row, label)} />
                      </td>
                    ))}
                    <td className="name">
                      <RecentRun row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="prose" style={{ marginTop: "var(--s-3)" }}>
            Counts are overs out of decided games; pushes are excluded. Windows are built only
            from games finished <em>before</em> this one, so a completed game is previewed with
            what was known at the time. A percentage is shown only once four games have been
            decided — five games is noise, and this is history, not a forecast.
          </p>
        </>
      )}
    </Async>
  );
}
