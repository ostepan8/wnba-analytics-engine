/* Score margin through a game.

   The x axis is play sequence rather than the clock: `clock` is a display
   string that restarts every period, so ordering by it interleaves the
   quarters. Period boundaries are drawn so the shape can be read against the
   structure of the game. */

import type { FlowPlay } from "../lib/api";
import { ChartFrame, useTooltip } from "./primitives";

const WIDTH = 760;
const HEIGHT = 250;
const PAD = { left: 44, right: 66, top: 18, bottom: 28 };

export default function GameFlow({
  plays,
  homeAbbr,
  awayAbbr,
}: {
  plays: FlowPlay[];
  homeAbbr: string;
  awayAbbr: string;
}) {
  const { ref, show, hide, element } = useTooltip();
  if (plays.length < 2) return <p className="empty">No play-by-play recorded.</p>;

  const bound = Math.max(8, ...plays.map((play) => Math.abs(play.margin)));
  const X = (index: number) =>
    PAD.left + (index / (plays.length - 1)) * (WIDTH - PAD.left - PAD.right);
  const Y = (margin: number) =>
    PAD.top + (1 - (margin + bound) / (2 * bound)) * (HEIGHT - PAD.top - PAD.bottom);

  // Whole numbers: a margin is points, and a gridline at "-4.5" is not a score.
  const step = Math.max(1, Math.round(bound / 2));
  const ticks = [-2 * step, -step, 0, step, 2 * step].filter((v) => Math.abs(v) <= bound);

  const boundaries: { index: number; period: number }[] = [];
  plays.forEach((play, index) => {
    if (index > 0 && play.period !== plays[index - 1].period) {
      boundaries.push({ index, period: play.period });
    }
  });

  const last = plays[plays.length - 1];

  return (
    <ChartFrame innerRef={ref} tooltip={element}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Score margin through the game">
        {ticks.map((margin) => (
          <g key={margin}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={Y(margin)}
              y2={Y(margin)}
              stroke={margin === 0 ? "var(--line-strong)" : "var(--line)"}
              strokeWidth={1}
            />
            <text x={PAD.left - 8} y={Y(margin) + 4} textAnchor="end">
              {margin > 0 ? `+${margin}` : margin}
            </text>
          </g>
        ))}

        {boundaries.map((boundary) => (
          <g key={boundary.index}>
            <line
              x1={X(boundary.index)}
              x2={X(boundary.index)}
              y1={PAD.top}
              y2={HEIGHT - PAD.bottom}
              stroke="var(--line)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text x={X(boundary.index) + 4} y={PAD.top + 10}>
              Q{boundary.period}
            </text>
          </g>
        ))}

        <path
          d={plays.map((play, index) => `${index ? "L" : "M"}${X(index)} ${Y(play.margin)}`).join(" ")}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
        />

        {/* away–home, matching how the score reads everywhere else on the site. */}
        <text x={X(plays.length - 1) + 7} y={Y(last.margin) + 4} style={{ fill: "var(--ink-2)" }}>
          {last.away_score}–{last.home_score}
        </text>
        <text x={WIDTH - PAD.right + 6} y={PAD.top + 10}>
          {homeAbbr} ahead
        </text>
        <text x={WIDTH - PAD.right + 6} y={HEIGHT - PAD.bottom - 2}>
          {awayAbbr} ahead
        </text>

        <rect
          x={PAD.left}
          y={PAD.top}
          width={WIDTH - PAD.left - PAD.right}
          height={HEIGHT - PAD.top - PAD.bottom}
          fill="transparent"
          onPointerMove={(event) => {
            const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
            const ratio =
              (((event.clientX - box.left) / box.width) * WIDTH - PAD.left) /
              (WIDTH - PAD.left - PAD.right);
            const index = Math.max(
              0,
              Math.min(plays.length - 1, Math.round(ratio * (plays.length - 1))),
            );
            const play = plays[index];
            show(
              event,
              <>
                <strong>
                  Q{play.period} {play.clock ?? ""}
                </strong>
                <div className="tooltip__row">
                  {awayAbbr} {play.away_score} – {play.home_score} {homeAbbr}
                </div>
                {play.description && (
                  <div
                    className="tooltip__row"
                    style={{ maxWidth: 260, whiteSpace: "normal" }}
                  >
                    {play.description.slice(0, 90)}
                  </div>
                )}
              </>,
            );
          }}
          onPointerLeave={hide}
        />
      </svg>
    </ChartFrame>
  );
}
