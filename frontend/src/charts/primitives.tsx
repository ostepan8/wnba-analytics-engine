/* Chart primitives, hand-built in SVG.

   No charting library: every chart here needs behaviour a general-purpose
   library makes awkward (a basketball court, a diverging scale centred on a
   value the API returns, a margin axis in whole points), and the shared parts
   are small enough that owning them costs less than configuring around them.

   Shared rules, applied here so no individual chart has to remember them:
   2px lines, ≥8px markers, recessive grid, tabular numerals, a tooltip on
   anything with marks, and colour that always has a text or shape partner. */

import { useCallback, useRef, useState, type ReactNode } from "react";

export interface TooltipState {
  x: number;
  y: number;
  content: ReactNode;
}

/** Positions a tooltip inside the chart box and keeps it from running off. */
export function useTooltip() {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const show = useCallback((event: { clientX: number; clientY: number }, content: ReactNode) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    setTip({
      x: Math.min(Math.max(event.clientX - box.left + 14, 0), Math.max(box.width - 230, 0)),
      y: Math.max(event.clientY - box.top - 12, 0),
      content,
    });
  }, []);

  const hide = useCallback(() => setTip(null), []);

  const element = tip ? (
    <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
      {tip.content}
    </div>
  ) : null;

  return { ref, show, hide, element };
}

export function ChartFrame({
  children,
  tooltip,
  innerRef,
}: {
  children: ReactNode;
  tooltip?: ReactNode;
  innerRef?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="chart" ref={innerRef}>
      {children}
      {tooltip}
    </div>
  );
}

export function Swatch({ color }: { color: string }) {
  return <span className="swatch" style={{ background: color }} />;
}

/** Horizontal bars: magnitude ranked by identity. One series, so no legend --
    the panel title names it. Every bar is directly labelled. */
export function BarList({
  rows,
  labelWidth = 150,
  onHover,
  format = (value) => value.toFixed(1),
}: {
  rows: { key: string | number; label: string; value: number; node?: ReactNode }[];
  labelWidth?: number;
  onHover?: (key: string | number, event: React.PointerEvent) => void;
  format?: (value: number) => string;
}) {
  if (!rows.length) return null;
  const width = 720;
  const rowHeight = 30;
  const right = 56;
  const max = Math.max(...rows.map((row) => row.value));

  return (
    <svg viewBox={`0 0 ${width} ${rows.length * rowHeight + 6}`} role="img">
      {rows.map((row, index) => {
        const y = index * rowHeight;
        const barWidth = Math.max((row.value / max) * (width - labelWidth - right), 2);
        return (
          <g
            key={row.key}
            onPointerEnter={(event) => onHover?.(row.key, event)}
            onPointerLeave={() => onHover?.(row.key, event as never)}
          >
            <rect x={0} y={y} width={width} height={rowHeight} fill="transparent" />
            <text x={labelWidth - 12} y={y + 19} textAnchor="end" style={{ fill: "var(--ink-2)" }}>
              {row.label}
            </text>
            <rect
              x={labelWidth}
              y={y + 8}
              width={barWidth}
              height={14}
              rx={4}
              fill="var(--series-1)"
            />
            <text x={labelWidth + barWidth + 8} y={y + 20} style={{ fill: "var(--ink-2)" }}>
              {format(row.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export interface SeriesPoint {
  t: number;
  v: number;
}

export interface Series {
  key: string;
  label: string;
  color: string;
  points: SeriesPoint[];
}

/** Multi-series time chart with a crosshair. One y-axis, always: two measures
    of different scale get two charts, never two scales. */
export function TimeSeries({
  series,
  height = 220,
  domain = [0, 1],
  formatValue,
  formatTime,
}: {
  series: Series[];
  height?: number;
  domain?: [number, number];
  formatValue: (value: number) => string;
  formatTime: (time: number) => string;
}) {
  const { ref, show, hide, element } = useTooltip();
  const present = series.filter((entry) => entry.points.length > 0);
  if (!present.length) return <p className="empty">No data recorded.</p>;

  const width = 760;
  const pad = { left: 46, right: 62, top: 14, bottom: 26 };
  const all = present.flatMap((entry) => entry.points);
  const t0 = Math.min(...all.map((point) => point.t));
  const t1 = Math.max(...all.map((point) => point.t));
  const [lo, hi] = domain;

  const X = (t: number) =>
    pad.left + ((t - t0) / Math.max(t1 - t0, 1)) * (width - pad.left - pad.right);
  const Y = (v: number) =>
    pad.top + (1 - (v - lo) / (hi - lo)) * (height - pad.top - pad.bottom);

  const ticks = [lo, (lo + hi) / 2, hi];

  return (
    <ChartFrame innerRef={ref} tooltip={element}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        {ticks.map((value) => (
          <g key={value}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={Y(value)}
              y2={Y(value)}
              stroke={value === (lo + hi) / 2 ? "var(--line-strong)" : "var(--line)"}
              strokeWidth={1}
            />
            <text x={pad.left - 8} y={Y(value) + 4} textAnchor="end">
              {formatValue(value)}
            </text>
          </g>
        ))}

        {present.map((entry) => {
          const sorted = [...entry.points].sort((a, b) => a.t - b.t);
          const last = sorted[sorted.length - 1];
          return (
            <g key={entry.key}>
              <path
                d={sorted.map((p, i) => `${i ? "L" : "M"}${X(p.t)} ${Y(p.v)}`).join(" ")}
                fill="none"
                stroke={entry.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              <text x={X(last.t) + 7} y={Y(last.v) + 4} style={{ fill: "var(--ink-2)" }}>
                {formatValue(last.v)}
              </text>
            </g>
          );
        })}

        <rect
          x={pad.left}
          y={pad.top}
          width={width - pad.left - pad.right}
          height={height - pad.top - pad.bottom}
          fill="transparent"
          onPointerMove={(event) => {
            const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
            const t =
              t0 +
              (((event.clientX - box.left) / box.width) * width - pad.left) /
                (width - pad.left - pad.right) *
                (t1 - t0);
            show(
              event,
              <>
                <strong>{formatTime(t)}</strong>
                {present.map((entry) => {
                  const near = entry.points.reduce((a, b) =>
                    Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a,
                  );
                  return (
                    <div className="tooltip__row" key={entry.key}>
                      <Swatch color={entry.color} />
                      {entry.label}: <strong>{formatValue(near.v)}</strong>
                    </div>
                  );
                })}
              </>,
            );
          }}
          onPointerLeave={hide}
        />
      </svg>
    </ChartFrame>
  );
}
