/* Individual shots for one game.
 *
 * A season chart bins 30,000 attempts because no one can read 30,000 marks. One
 * team in one game is about sixty-five, and binning those onto the same grid
 * leaves most cells holding a single shot — the chart becomes scattered noise
 * that says nothing, because there is nothing to average.
 *
 * So at this grain the mark IS the shot. Made and missed are separated by shape
 * as well as colour (filled disc versus hollow ring), so the distinction
 * survives colourblindness, greyscale printing and a small screen.
 */

import type { GameShotPoint } from "../lib/api";
import { ChartFrame, useTooltip } from "./primitives";

const COURT = { minX: -250, maxX: 250, minY: -50, maxY: 400 };
const SY = (y: number) => COURT.maxY - y;
const THREE_RADIUS = 221;
const CORNER_X = 220;
const BASELINE = -47.5;
const FT_LINE = 142.5;

/* Sweep-flag 1 throughout: SY() flips the y axis, and in SVG's y-down space
   that is the direction a left-to-right arc bulges away from the baseline. */
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

export default function GameShotPlot({ shots }: { shots: GameShotPoint[] }) {
  const { ref, show, hide, element } = useTooltip();
  if (!shots.length) return null;

  const made = shots.filter((shot) => shot.made).length;

  return (
    <ChartFrame innerRef={ref} tooltip={element}>
      <svg
        viewBox={`${COURT.minX - 8} ${SY(COURT.maxY) - 8} ${COURT.maxX - COURT.minX + 16} ${
          SY(COURT.minY) - SY(COURT.maxY) + 16
        }`}
        role="img"
        aria-label={`${shots.length} shots, ${made} made`}
      >
        <Court />
        {shots.map((shot, index) => {
          const cx = shot.loc_x;
          const cy = SY(shot.loc_y);
          const tip = (
            <>
              <strong>{shot.player_name ?? "Unknown"}</strong>
              <div className="tooltip__row">
                {shot.made ? "Made" : "Missed"} {shot.shot_value}pt · {shot.shot_distance} ft
              </div>
              <div className="tooltip__row">
                Q{shot.period} · {shot.shot_zone_basic ?? shot.action_type ?? ""}
              </div>
            </>
          );
          const handlers = {
            onPointerEnter: (event: React.PointerEvent) => show(event, tip),
            onPointerLeave: hide,
          };
          // Filled = made, hollow = missed. Shape carries it as well as colour.
          return shot.made ? (
            <circle
              key={index}
              cx={cx}
              cy={cy}
              r={7}
              fill="var(--series-1)"
              stroke="var(--surface)"
              strokeWidth={1.5}
              {...handlers}
            />
          ) : (
            <circle
              key={index}
              cx={cx}
              cy={cy}
              r={6.5}
              fill="none"
              stroke="var(--series-2)"
              strokeWidth={2.5}
              {...handlers}
            />
          );
        })}
      </svg>
      <div className="legend" style={{ marginTop: "var(--s-2)" }}>
        <span>
          <svg width="14" height="14" style={{ overflow: "visible" }}>
            <circle cx="7" cy="7" r="6" fill="var(--series-1)" />
          </svg>
          Made ({made})
        </span>
        <span>
          <svg width="14" height="14" style={{ overflow: "visible" }}>
            <circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--series-2)" strokeWidth="2.5" />
          </svg>
          Missed ({shots.length - made})
        </span>
        <span className="muted">
          {((made / shots.length) * 100).toFixed(1)}% on {shots.length} attempts
        </span>
      </div>
    </ChartFrame>
  );
}
