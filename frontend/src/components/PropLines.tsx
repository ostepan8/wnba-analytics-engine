/* Closing prop lines against what the player actually did.
 *
 * Read-only history. Nothing here is a recommendation: the league-wide over
 * rate sits at 44-49% across every market, which looks like a standing edge on
 * unders and is not one -- graded at prices that could actually be taken,
 * blanket under-betting returns -2.05% to -10.68% (MODELING_FINDINGS.md). The
 * vig is bigger than the bias.
 *
 * So the framing is descriptive: here is where the market set the number, here
 * is what happened, count them yourself.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { Async, Panel } from "./ui";
import type { PropLogRow, PropSummaryRow } from "../lib/api";
import { propLabel, useQuery } from "../lib/api";
import { pct, shortDate } from "../lib/format";
import { ChartFrame, useTooltip } from "../charts/primitives";

interface PropsResponse {
  player_id: number;
  summary: PropSummaryRow[];
  prop_type: string | null;
  log: PropLogRow[];
}

/** Line against realized, so the gap is visible rather than inferred. */
function LineVsResult({ rows }: { rows: PropLogRow[] }) {
  const { ref, show, hide, element } = useTooltip();
  const ordered = [...rows].reverse(); // oldest first, so time reads left to right
  if (ordered.length < 2) return null;

  const width = 760;
  const height = 200;
  const pad = { left: 34, right: 16, top: 14, bottom: 24 };
  const values = ordered.flatMap((row) => [Number(row.line), row.realized]);
  const lo = Math.min(...values) - 1;
  const hi = Math.max(...values) + 1;

  const X = (index: number) =>
    pad.left + (index / Math.max(ordered.length - 1, 1)) * (width - pad.left - pad.right);
  const Y = (value: number) =>
    pad.top + (1 - (value - lo) / (hi - lo)) * (height - pad.top - pad.bottom);

  return (
    <ChartFrame innerRef={ref} tooltip={element}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Closing line against result">
        {[lo, (lo + hi) / 2, hi].map((value) => (
          <g key={value}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={Y(value)}
              y2={Y(value)}
              stroke="var(--line)"
              strokeWidth={1}
            />
            <text x={pad.left - 6} y={Y(value) + 4} textAnchor="end">
              {value.toFixed(0)}
            </text>
          </g>
        ))}

        {/* The line the market set. */}
        <path
          d={ordered.map((row, i) => `${i ? "L" : "M"}${X(i)} ${Y(Number(row.line))}`).join(" ")}
          fill="none"
          stroke="var(--ink-muted)"
          strokeWidth={2}
          strokeDasharray="5 4"
        />

        {/* What happened. Colour carries over/under, and the shape's position
            above or below the dashed line says the same thing again -- so the
            distinction never rests on colour alone. */}
        {ordered.map((row, i) => (
          <circle
            key={row.game_id}
            cx={X(i)}
            cy={Y(row.realized)}
            r={5}
            fill={
              row.result === "over"
                ? "var(--div-high)"
                : row.result === "under"
                  ? "var(--div-low)"
                  : "var(--ink-muted)"
            }
            stroke="var(--surface)"
            strokeWidth={2}
            onPointerEnter={(event) =>
              show(
                event,
                <>
                  <strong>{shortDate(row.start_time)}</strong> vs {row.opponent_abbr}
                  <div className="tooltip__row">
                    line {row.line} · actual <strong>{row.realized}</strong> ({row.result})
                  </div>
                  <div className="tooltip__row">{row.books} books</div>
                </>,
              )
            }
            onPointerLeave={hide}
          />
        ))}
      </svg>
      <div className="legend" style={{ marginTop: "var(--s-2)" }}>
        <span>
          <span
            style={{
              width: 16,
              height: 0,
              borderTop: "2px dashed var(--ink-muted)",
              display: "inline-block",
            }}
          />
          Closing line
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--div-high)" }} />
          Over
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--div-low)" }} />
          Under
        </span>
      </div>
    </ChartFrame>
  );
}

export default function PropLines({ playerId }: { playerId: number }) {
  const [selected, setSelected] = useState<string | null>(null);
  const query = useQuery<PropsResponse>(
    `/players/${playerId}/props?limit=40${selected ? `&prop_type=${selected}` : ""}`,
  );

  return (
    <Panel
      title="Prop lines vs results"
      hint="Closing consensus, pushes excluded from the rates"
    >
      <Async query={query} empty={(data) => data.summary.length === 0}>
        {(data) => {
          const active = selected ?? data.prop_type;
          return (
            <>
              <div className="table-wrap" style={{ marginBottom: "var(--s-4)" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Market</th>
                      <th>G</th>
                      <th>Avg line</th>
                      <th>Avg actual</th>
                      <th>Over</th>
                      <th>Under</th>
                      <th>Over rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.summary.map((row) => {
                      const decided = row.overs + row.unders;
                      return (
                        <tr
                          key={row.prop_type}
                          role="button"
                          tabIndex={0}
                          aria-pressed={row.prop_type === active}
                          onClick={() => setSelected(row.prop_type)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelected(row.prop_type);
                            }
                          }}
                          style={{
                            cursor: "pointer",
                            background:
                              row.prop_type === active ? "var(--accent-wash)" : undefined,
                          }}
                        >
                          <td>{propLabel(row.prop_type)}</td>
                          <td>{row.games}</td>
                          <td>{row.avg_line ?? "—"}</td>
                          <td>{row.avg_realized ?? "—"}</td>
                          <td>{row.overs}</td>
                          <td>{row.unders}</td>
                          <td>{decided ? pct(row.overs / decided) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {data.log.length > 1 ? (
                <>
                  <p className="prose" style={{ marginBottom: "var(--s-2)" }}>
                    {propLabel(active ?? "")} — last {data.log.length} graded games.
                  </p>
                  <LineVsResult rows={data.log} />
                </>
              ) : (
                <p className="empty">Not enough graded games to chart.</p>
              )}

              <p className="prose" style={{ marginTop: "var(--s-3)" }}>
                Overs lose league-wide in every market, which looks like an edge on unders and is
                not one — graded at takeable prices, blanket under-betting returns −2% to −11%.
                The vig is larger than the bias.{" "}
                <Link to="/research" style={{ color: "var(--accent)" }}>
                  The research →
                </Link>
              </p>
            </>
          );
        }}
      </Async>
    </Panel>
  );
}
