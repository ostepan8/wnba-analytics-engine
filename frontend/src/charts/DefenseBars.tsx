/* What each side gives up, by position, read as one picture.
 *
 * A paired horizontal bar — away extending left, home extending right, the
 * position between them — because that is the shape the rest of this matchup
 * already has, and because the question is always comparative: a prop on a
 * guard is worth reading against whichever of these two defends guards worse.
 *
 * Both sides share ONE scale. Mirrored axes are not two axes; the measure,
 * units and pixels-per-point are identical left and right, which is the whole
 * reason the comparison is legible.
 *
 * Colour carries team identity and nothing else. Rank is the interesting part
 * but it is deliberately NOT a colour: shading by rank would repaint a team
 * when the league moves around it, and a reader would be decoding a legend
 * instead of reading a length. Rank travels as text, and the league average
 * as a tick, so "is this a lot" is answerable without leaving the chart.
 */

import type { DefenseByPositionRow } from "../lib/api";

const ROW_HEIGHT = 30;
const BAR_HEIGHT = 13;
const LABEL_WIDTH = 90;
const GUTTER = 8;

/* Room reserved OUTSIDE each bar for its value and rank. Without it the bars
   run to the edge of the viewBox and their labels are simply clipped away. */
const VALUE_WIDTH = 76;

/** Ordered so the row order is stable regardless of what the API returns. */
const POSITION_ORDER = ["G", "F", "C"];

function positionLabel(position: string) {
  if (position === "G") return "Guards";
  if (position === "F") return "Forwards";
  if (position === "C") return "Centers";
  return position;
}

interface Side {
  abbr: string;
  rows: DefenseByPositionRow[];
}

function rowFor(side: Side, position: string) {
  return side.rows.find((row) => row.position === position);
}

export default function DefenseBars({
  away,
  home,
  width = 900,
}: {
  away: Side;
  home: Side;
  width?: number;
}) {
  const positions = POSITION_ORDER.filter(
    (position) => rowFor(away, position) || rowFor(home, position),
  );
  if (positions.length === 0) return null;

  const values = positions.flatMap((position) =>
    [rowFor(away, position), rowFor(home, position)]
      .map((row) => Number(row?.points_allowed ?? 0))
      .filter((value) => value > 0),
  );
  const max = Math.max(...values, 1);

  const half = (width - LABEL_WIDTH) / 2 - GUTTER - VALUE_WIDTH;
  const centre = width / 2;
  const height = positions.length * ROW_HEIGHT + 26;
  const scale = (value: number) => (value / max) * half;

  return (
    <figure style={{ margin: 0 }}>
      {/* Two series, so a legend is always present — identity is never carried
          by colour alone. */}
      <div className="legend" style={{ marginBottom: "var(--s-2)" }}>
        <span>
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: 3,
              background: "var(--series-1)",
              display: "inline-block",
            }}
          />
          {away.abbr}
        </span>
        <span>
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: 3,
              background: "var(--series-2)",
              display: "inline-block",
            }}
          />
          {home.abbr}
        </span>
        <span className="muted" style={{ fontSize: "var(--t-xs)" }}>
          points allowed per opposing player-game · tick = league average
        </span>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img"
        aria-label={`Points allowed by position, ${away.abbr} versus ${home.abbr}`}>
        {positions.map((position, index) => {
          const y = index * ROW_HEIGHT + 8;
          const mid = y + BAR_HEIGHT / 2;
          const a = rowFor(away, position);
          const h = rowFor(home, position);
          const aValue = Number(a?.points_allowed ?? 0);
          const hValue = Number(h?.points_allowed ?? 0);
          const average = Number(a?.points_allowed_league_avg ?? h?.points_allowed_league_avg ?? 0);

          return (
            <g key={position}>
              <text
                x={centre}
                y={mid + 4}
                textAnchor="middle"
                style={{
                  fontSize: 12,
                  fill: "var(--ink-muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                {positionLabel(position)}
              </text>

              {/* League average, same scale on both sides. Painted before the
                  bars and their value/rank text below, not after: an SVG
                  paints later siblings over earlier ones, and this used to be
                  last -- drawing the tick on top of the text it frequently
                  sits beneath, slicing through the digits, since the two are
                  positioned independently and land close together whenever a
                  team's own value is near the league average (the normal
                  case). Text painted on top of the tick instead keeps every
                  digit intact; the tick still reads fine passing near/through
                  the letter-spacing gaps around it. */}
              {average > 0 &&
                [
                  centre - LABEL_WIDTH / 2 - GUTTER - scale(average),
                  centre + LABEL_WIDTH / 2 + GUTTER + scale(average),
                ].map((x) => (
                  <line
                    key={x}
                    x1={x}
                    x2={x}
                    y1={y - 3}
                    y2={y + BAR_HEIGHT + 3}
                    stroke="var(--line-strong)"
                    strokeWidth={2}
                  />
                ))}

              {a && aValue > 0 && (
                <g>
                  {/* Rounded data-end away from the baseline; the baseline end
                      stays square where it meets the centre. */}
                  <rect
                    x={centre - LABEL_WIDTH / 2 - GUTTER - scale(aValue)}
                    y={y}
                    width={scale(aValue)}
                    height={BAR_HEIGHT}
                    rx={4}
                    fill="var(--series-1)"
                  >
                    <title>
                      {`${away.abbr} allows ${aValue} to ${positionLabel(position)} — ` +
                        `${a.points_allowed_rank} of ${a.teams_ranked} in the league`}
                    </title>
                  </rect>
                  <text
                    x={centre - LABEL_WIDTH / 2 - GUTTER - scale(aValue) - 6}
                    y={mid + 4}
                    textAnchor="end"
                    style={{ fontSize: 13, fill: "var(--ink-2)" }}
                  >
                    {aValue}
                    <tspan style={{ fill: "var(--ink-muted)" }}>
                      {`  #${a.points_allowed_rank}`}
                    </tspan>
                  </text>
                </g>
              )}

              {h && hValue > 0 && (
                <g>
                  <rect
                    x={centre + LABEL_WIDTH / 2 + GUTTER}
                    y={y}
                    width={scale(hValue)}
                    height={BAR_HEIGHT}
                    rx={4}
                    fill="var(--series-2)"
                  >
                    <title>
                      {`${home.abbr} allows ${hValue} to ${positionLabel(position)} — ` +
                        `${h.points_allowed_rank} of ${h.teams_ranked} in the league`}
                    </title>
                  </rect>
                  <text
                    x={centre + LABEL_WIDTH / 2 + GUTTER + scale(hValue) + 6}
                    y={mid + 4}
                    style={{ fontSize: 13, fill: "var(--ink-2)" }}
                  >
                    {hValue}
                    <tspan style={{ fill: "var(--ink-muted)" }}>
                      {`  #${h.points_allowed_rank}`}
                    </tspan>
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
