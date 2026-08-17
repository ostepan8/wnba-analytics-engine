/* Usage against true shooting: volume separated from value.

   League-average crosshairs make the quadrants readable -- without a reference
   line a scatter is just a cloud. Labels are placed only where they will not
   collide with one already drawn; overlapping names are worse than none. */

import { Link } from "react-router-dom";
import type { EfficiencyRow } from "../lib/api";
import { pct } from "../lib/format";
import { ChartFrame, useTooltip } from "./primitives";

const WIDTH = 760;
const HEIGHT = 420;
const PAD = { left: 54, right: 22, top: 16, bottom: 46 };

export default function EfficiencyScatter({ players }: { players: EfficiencyRow[] }) {
  const { ref, show, hide, element } = useTooltip();
  const usable = players.filter(
    (player) => player.usage_pct !== null && player.true_shooting !== null,
  );
  if (usable.length < 2) return <p className="empty">Not enough qualifying players.</p>;

  const xs = usable.map((p) => Number(p.usage_pct));
  const ys = usable.map((p) => Number(p.true_shooting));
  const x0 = Math.min(...xs) - 0.01;
  const x1 = Math.max(...xs) + 0.01;
  const y0 = Math.min(...ys) - 0.02;
  const y1 = Math.max(...ys) + 0.02;

  const X = (v: number) => PAD.left + ((v - x0) / (x1 - x0)) * (WIDTH - PAD.left - PAD.right);
  const Y = (v: number) =>
    PAD.top + (1 - (v - y0) / (y1 - y0)) * (HEIGHT - PAD.top - PAD.bottom);

  const meanX = xs.reduce((a, b) => a + b, 0) / xs.length;
  const meanY = ys.reduce((a, b) => a + b, 0) / ys.length;
  const maxMinutes = Math.max(...usable.map((p) => Number(p.minutes) || 0), 1);

  // Draw largest first so small bubbles stay reachable on top of big ones.
  const ordered = [...usable].sort((a, b) => Number(b.minutes) - Number(a.minutes));

  const placed: { x: number; y: number; w: number }[] = [];
  const labelled = [...usable]
    .sort(
      (a, b) =>
        Number(b.usage_pct) + Number(b.true_shooting) -
        (Number(a.usage_pct) + Number(a.true_shooting)),
    )
    .filter((player) => {
      if (placed.length >= 4) return false;
      const x = X(Number(player.usage_pct)) + 12;
      const y = Y(Number(player.true_shooting)) + 4;
      const w = player.full_name.length * 6.2;
      const clash = placed.some(
        (other) => Math.abs(other.y - y) < 14 && x < other.x + other.w + 6 && x + w + 6 > other.x,
      );
      if (clash) return false;
      placed.push({ x, y, w });
      return true;
    });

  return (
    <ChartFrame innerRef={ref} tooltip={element}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Usage rate against true shooting">
        {[0, 1, 2, 3, 4].map((step) => {
          const value = y0 + ((y1 - y0) * step) / 4;
          return (
            <g key={step}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={Y(value)}
                y2={Y(value)}
                stroke="var(--line)"
                strokeWidth={1}
              />
              <text x={PAD.left - 8} y={Y(value) + 4} textAnchor="end">
                {pct(value, 0)}
              </text>
            </g>
          );
        })}
        {[0, 1, 2, 3, 4].map((step) => {
          const value = x0 + ((x1 - x0) * step) / 4;
          return (
            <text key={step} x={X(value)} y={HEIGHT - PAD.bottom + 18} textAnchor="middle">
              {pct(value, 0)}
            </text>
          );
        })}

        <path
          d={`M${X(meanX)} ${PAD.top} V${HEIGHT - PAD.bottom}`}
          stroke="var(--line-strong)"
          strokeDasharray="4 4"
          strokeWidth={1}
        />
        <path
          d={`M${PAD.left} ${Y(meanY)} H${WIDTH - PAD.right}`}
          stroke="var(--line-strong)"
          strokeDasharray="4 4"
          strokeWidth={1}
        />
        <text x={X(meanX) + 5} y={HEIGHT - PAD.bottom - 6}>
          avg usage
        </text>
        <text x={PAD.left + 6} y={Y(meanY) - 6}>
          avg TS%
        </text>
        <text x={(PAD.left + WIDTH - PAD.right) / 2} y={HEIGHT - 6} textAnchor="middle">
          Usage rate →
        </text>

        {ordered.map((player) => (
          <circle
            key={player.player_id}
            cx={X(Number(player.usage_pct))}
            cy={Y(Number(player.true_shooting))}
            r={4 + 7 * Math.sqrt((Number(player.minutes) || 0) / maxMinutes)}
            fill="var(--series-1)"
            fillOpacity={0.62}
            stroke="var(--surface)"
            strokeWidth={2}
            onPointerEnter={(event) =>
              show(
                event,
                <>
                  <strong>{player.full_name}</strong> · {player.team_abbr}
                  <div className="tooltip__row">
                    {pct(player.usage_pct)} usage · {pct(player.true_shooting)} TS
                  </div>
                  <div className="tooltip__row">
                    {player.minutes} min · {player.games_played} games
                  </div>
                </>,
              )
            }
            onPointerLeave={hide}
          />
        ))}

        {labelled.map((player) => (
          <text
            key={`label-${player.player_id}`}
            x={X(Number(player.usage_pct)) + 12}
            y={Y(Number(player.true_shooting)) + 4}
            style={{ fill: "var(--ink-2)" }}
          >
            {player.full_name}
          </text>
        ))}
      </svg>
      <p className="prose" style={{ marginTop: "var(--s-2)" }}>
        High and to the right is the valuable quadrant: heavy load carried at good efficiency.
        Bubble size is minutes per game.{" "}
        {labelled[0] && (
          <Link to={`/players/${labelled[0].player_id}`} style={{ color: "var(--accent)" }}>
            {labelled[0].full_name} →
          </Link>
        )}
      </p>
    </ChartFrame>
  );
}
