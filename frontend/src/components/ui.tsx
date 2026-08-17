/* The primitive set. Every page composes from these; none of them restyles
   another. Keeping the vocabulary this small is what makes separate pages look
   like one product rather than several. */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { playerImage, teamLogo } from "../lib/api";

export function Panel({
  title,
  hint,
  tools,
  flush,
  children,
}: {
  title?: string;
  hint?: string;
  tools?: ReactNode;
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      {(title || tools) && (
        <header className="panel__head">
          {title && <h3 className="panel__title">{title}</h3>}
          {hint && <span className="panel__hint">{hint}</span>}
          {tools && <div className="panel__tools">{tools}</div>}
        </header>
      )}
      <div className={flush ? "panel__body panel__body--flush" : "panel__body"}>{children}</div>
    </section>
  );
}

export function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="section__head">
        <h2 className="section__title">{title}</h2>
        {note && <p className="section__note">{note}</p>}
      </div>
      {children}
    </section>
  );
}

export function Stat({
  value,
  label,
  detail,
}: {
  value: ReactNode;
  label: string;
  detail?: ReactNode;
}) {
  return (
    <div className="stat">
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
      {detail && <span className="stat__detail">{detail}</span>}
    </div>
  );
}

/* Images are decorative here -- every one sits beside the name it depicts, so
   alt text would be read out twice by a screen reader. onError hides a missing
   asset rather than leaving a broken-image glyph: 175 of 579 players have no
   upstream headshot, so this is the normal case, not an exception. */
const hideOnError = (event: { currentTarget: HTMLImageElement }) => {
  event.currentTarget.style.visibility = "hidden";
};

export function TeamLogo({
  teamId,
  size = "md",
}: {
  teamId: number | null | undefined;
  size?: "sm" | "md" | "lg";
}) {
  const src = teamLogo(teamId);
  if (!src) return <span className={`logo logo--${size}`} />;
  return <img className={`logo logo--${size}`} src={src} alt="" loading="lazy" onError={hideOnError} />;
}

export function PlayerAvatar({
  playerId,
  size = "sm",
}: {
  playerId: number | null | undefined;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const src = playerImage(playerId);
  if (!src) return <span className={`avatar avatar--${size}`} />;
  return (
    <img className={`avatar avatar--${size}`} src={src} alt="" loading="lazy" onError={hideOnError} />
  );
}

export function PlayerCell({
  playerId,
  name,
  meta,
  size = "sm",
}: {
  playerId: number;
  name: string;
  meta?: string;
  size?: "sm" | "md";
}) {
  return (
    <Link className="identity" to={`/players/${playerId}`}>
      <PlayerAvatar playerId={playerId} size={size} />
      <span style={{ minWidth: 0 }}>
        <span className="identity__name">{name}</span>
        {meta && (
          <>
            <br />
            <span className="identity__meta">{meta}</span>
          </>
        )}
      </span>
    </Link>
  );
}

export function TeamCell({
  teamId,
  name,
  meta,
  size = "sm",
}: {
  teamId: number;
  name: string;
  meta?: string;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <Link className="identity" to={`/teams/${teamId}`}>
      <TeamLogo teamId={teamId} size={size} />
      <span style={{ minWidth: 0 }}>
        <span className="identity__name">{name}</span>
        {meta && (
          <>
            <br />
            <span className="identity__meta">{meta}</span>
          </>
        )}
      </span>
    </Link>
  );
}

/** The fields a playoff-race badge needs. Both `StandingRow` (the full league
 *  table) and `StandingRowLite` (what a team profile carries) satisfy this
 *  structurally — `StandingRowLite` just omits `magic_number` and
 *  `in_playoff_position`, which are treated as optional here. */
export interface RaceStatus {
  clinched?: boolean;
  eliminated?: boolean;
  in_playoff_position?: boolean;
  magic_number?: number | null;
  games_behind_playoff?: number | null;
}

/**
 * Mathematical status ONLY — never position.
 *
 * "Above the line" and "clinched" are different claims, and so are "below the
 * line" and "eliminated". Collapsing either pair turns a standings table into
 * misinformation: a ninth-placed team with fifteen games left is not out, and
 * saying so is worse than saying nothing.
 */
export function RaceBadge({ status }: { status: RaceStatus }) {
  if (status.clinched) {
    return (
      <span className="badge badge--good" title="Cannot be caught for a top-eight finish">
        ✓ Clinched
      </span>
    );
  }
  if (status.eliminated) {
    return (
      <span className="badge badge--bad" title="Cannot reach a top-eight finish, whatever happens">
        ✕ Eliminated
      </span>
    );
  }
  // StandingRowLite has no in_playoff_position — "0 games behind the last
  // playoff spot" means the same thing and is what's actually available there.
  const inPosition = status.in_playoff_position ?? status.games_behind_playoff === 0;
  if (inPosition) {
    return (
      <span className="badge" title="Holding a place, but not yet mathematically safe">
        In position
        {status.magic_number != null && ` · magic ${status.magic_number}`}
      </span>
    );
  }
  return (
    <span className="badge" title="Outside the eight, but still mathematically alive">
      Still alive
      {status.games_behind_playoff ? ` · ${status.games_behind_playoff} back` : ""}
    </span>
  );
}

/** A clickable table header cell wired to `useSort`. `aria-sort` carries the
 *  state to assistive tech; the glyph is `aria-hidden` since it repeats what
 *  `aria-sort` already says. */
export function SortTh<K extends string>({
  label,
  column,
  active,
  direction,
  onSort,
}: {
  label: string;
  column: K;
  active: boolean;
  direction: "asc" | "desc";
  onSort: (column: K) => void;
}) {
  return (
    <th aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort-th" onClick={() => onSort(column)}>
        {label}
        <span aria-hidden="true" className={active ? "sort-th__arrow" : "sort-th__arrow sort-th__arrow--dim"}>
          {active && direction === "asc" ? "▲" : "▼"}
        </span>
      </button>
    </th>
  );
}

export function SeasonPicker({
  season,
  seasons,
  onChange,
}: {
  season: number;
  seasons: number[];
  onChange: (season: number) => void;
}) {
  return (
    <select
      className="control"
      value={season}
      aria-label="Season"
      onChange={(event) => onChange(Number(event.target.value))}
    >
      {seasons.map((year) => (
        <option key={year} value={year}>
          {year}
        </option>
      ))}
    </select>
  );
}

/* A skeleton rather than a spinner: the layout is already the right shape when
   data lands, so nothing jumps. */
export function Skeleton({ rows = 5, height = 28 }: { rows?: number; height?: number }) {
  return (
    <div style={{ display: "grid", gap: "var(--s-2)" }}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton" style={{ height }} />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

/**
 * One place that decides what "loading", "failed" and "nothing here" look like.
 *
 * Distinguishing empty from failed matters: an empty roster and an API error
 * both render as no rows, and telling a user "no data" when the request
 * actually failed sends them looking for the wrong problem.
 */
export function Async<T>({
  query,
  empty,
  skeleton,
  children,
}: {
  query: { data: T | undefined; error: Error | undefined; loading: boolean };
  empty?: (data: T) => boolean;
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.loading) return <>{skeleton ?? <Skeleton />}</>;
  if (query.error) return <Empty>Could not load this: {query.error.message}</Empty>;
  if (query.data === undefined) return <Empty>No data.</Empty>;
  if (empty?.(query.data)) return <Empty>Nothing recorded here yet.</Empty>;
  return <>{children(query.data)}</>;
}
