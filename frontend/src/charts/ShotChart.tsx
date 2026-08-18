/* A half-court shot chart.

   Coordinates are the provider's standard system in tenths of a foot: the hoop
   is the origin, x runs across the floor, y runs toward half court. SY() flips
   y for SVG so the hoop sits at the bottom of the screen the way every shot
   chart is drawn.

   Every arc carries sweep-flag 1, and that is load-bearing rather than
   cosmetic: with y flipped, sweep=1 is the direction that bulges a
   left-to-right arc upward -- away from the baseline, which is where all of a
   court's arcs open. Sweep=0 mirrors each one, which draws the three-point line
   curving off the bottom of the card.

   Colour is points per attempt on a diverging scale, never field-goal
   percentage. A 35% three and a 35% layup are not the same shot, so one FG%
   ramp paints the entire arc as poor. */

import type { ShotCell } from "../lib/api";
import { ChartFrame, useTooltip } from "./primitives";

const COURT = { minX: -250, maxX: 250, minY: -50, maxY: 400 };
const SY = (y: number) => COURT.maxY - y;

/* Measured from the data rather than assumed: the shortest recorded
   above-the-break three sits at radius 219, which is WNBA's 22'1.75" line, not
   the NBA's 237.5. */
const THREE_RADIUS = 221;
const CORNER_X = 220;

const BASELINE = -47.5;
const FT_LINE = 142.5;

function Court() {
  const join = Math.sqrt(THREE_RADIUS * THREE_RADIUS - CORNER_X * CORNER_X);
  return (
    <g fill="none" stroke="var(--line-strong)" strokeWidth={2} strokeLinecap="round">
      <path d={`M-250 ${SY(BASELINE)} H250`} />
      <path d={`M-250 ${SY(BASELINE)} V${SY(COURT.maxY)} M250 ${SY(BASELINE)} V${SY(COURT.maxY)}`} />
      <rect x={-80} y={SY(FT_LINE)} width={160} height={SY(BASELINE) - SY(FT_LINE)} />
      <path d={`M-60 ${SY(FT_LINE)} A60 60 0 0 1 60 ${SY(FT_LINE)}`} />
      <circle cx={0} cy={SY(0)} r={7.5} />
      <path d={`M-30 ${SY(-7.5)} H30`} />
      <path d={`M-40 ${SY(0)} A40 40 0 0 1 40 ${SY(0)}`} />
      <path
        d={
          `M${-CORNER_X} ${SY(BASELINE)} V${SY(join)} ` +
          `A${THREE_RADIUS} ${THREE_RADIUS} 0 0 1 ${CORNER_X} ${SY(join)} V${SY(BASELINE)}`
        }
      />
    </g>
  );
}

/** Diverging: red above the reference (a hot zone), blue below (cold),
 *  neutral at it -- the universal shot-chart convention. */
function cellColor(ppa: number, midpoint: number) {
  const spread = 0.45;
  const t = Math.max(-1, Math.min(1, (ppa - midpoint) / spread));
  const pole = t >= 0 ? "var(--div-red)" : "var(--div-blue)";
  return `color-mix(in oklab, ${pole} ${Math.round(Math.abs(t) * 100)}%, var(--div-mid))`;
}

export default function ShotChart({
  cells,
  binSize,
  midpoint,
  minAttempts = 3,
}: {
  cells: ShotCell[];
  binSize: number;
  midpoint: number;
  minAttempts?: number;
}) {
  const { ref, show, hide, element } = useTooltip();
  const visible = cells.filter((cell) => cell.attempts >= minAttempts);
  if (!visible.length) return <p className="empty">No shots recorded.</p>;

  const maxAttempts = Math.max(...visible.map((cell) => cell.attempts));

  return (
    <ChartFrame innerRef={ref} tooltip={element}>
      <svg
        viewBox={`${COURT.minX - 8} ${SY(COURT.maxY) - 8} ${COURT.maxX - COURT.minX + 16} ${
          SY(COURT.minY) - SY(COURT.maxY) + 16
        }`}
        role="img"
        aria-label="Shot chart coloured by points per attempt"
      >
        <Court />
        {visible.map((cell) => {
          const ppa = cell.points / cell.attempts;
          // Area tracks volume; sqrt so 4x the shots is 2x the width.
          const size = binSize * (0.35 + 0.65 * Math.sqrt(cell.attempts / maxAttempts));
          const cx = cell.x + binSize / 2;
          const cy = cell.y + binSize / 2;
          return (
            <rect
              key={`${cell.x}:${cell.y}`}
              x={cx - size / 2}
              y={SY(cy) - size / 2}
              width={size}
              height={size}
              rx={2}
              fill={cellColor(ppa, midpoint)}
              stroke="var(--surface)"
              strokeWidth={0.6}
              onPointerEnter={(event) =>
                show(
                  event,
                  <>
                    <strong>{cell.attempts} shots</strong> · {cell.makes} made
                    <div className="tooltip__row">
                      {((cell.makes / cell.attempts) * 100).toFixed(0)}% FG ·{" "}
                      <strong>{ppa.toFixed(2)}</strong> pts/att
                    </div>
                    <div className="tooltip__row">
                      {ppa - midpoint >= 0 ? "+" : ""}
                      {(ppa - midpoint).toFixed(2)} vs league
                    </div>
                  </>,
                )
              }
              onPointerLeave={hide}
            />
          );
        })}
      </svg>
    </ChartFrame>
  );
}

export function ShotChartLegend() {
  return (
    <span className="legend" style={{ fontSize: "var(--t-xs)" }}>
      <span>
        Below avg
        <span
          style={{
            width: 110,
            height: 9,
            borderRadius: 5,
            background:
              "linear-gradient(90deg, var(--div-blue), var(--div-mid), var(--div-red))",
          }}
        />
        Above avg
      </span>
    </span>
  );
}
