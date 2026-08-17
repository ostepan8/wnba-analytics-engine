/* Injury designations, ranked and coloured in one place.
 *
 * Two sources feed this. The league's own report files the real game-status
 * designations — Probable, Questionable, Doubtful, Out — and ESPN publishes
 * only Out and Day-To-Day for the WNBA. The API prefers the league's answer per
 * player and falls back to ESPN for anyone the report does not mention, so both
 * vocabularies reach the UI and both have to render sensibly.
 */

/** Most severe first. Unknown statuses sort last rather than in the middle,
 *  where they would read as a designation the league never filed. */
const ORDER = ["out", "doubtful", "day-to-day", "questionable", "probable", "available"];

function normalise(status: string | null | undefined): string {
  return (status ?? "").trim().toLowerCase();
}

export function statusRank(status: string | null | undefined): number {
  const index = ORDER.indexOf(normalise(status));
  return index === -1 ? ORDER.length : index;
}

/** Ruled out. Doubtful is "unlikely to play", which is not the same claim, so
 *  it is deliberately excluded — counting it as out overstates what was filed. */
export function isOut(status: string | null | undefined): boolean {
  return normalise(status) === "out";
}

/** The league's own report carries real designations (Probable, Questionable,
 *  Doubtful, Out); the ESPN fallback only ever says Out or Day-To-Day, which is
 *  a coarser claim wearing the same badge shape. Naming the source is the only
 *  way a reader can tell "Day-To-Day" apart from an actual game-status filing. */
export function sourceLabel(source: string | null | undefined): string | null {
  if (source === "wnba_official") return "league report";
  if (source === "espn") return "ESPN";
  return null;
}

export function badgeClass(status: string | null | undefined): string {
  const value = normalise(status);
  if (value === "out" || value === "doubtful") return "badge badge--bad";
  if (value === "questionable" || value === "day-to-day") return "badge badge--warn";
  if (value === "probable" || value === "available") return "badge badge--good";
  return "badge";
}

/** The league prints "Injury/Illness - Right Ankle; right ankle" — the half
 *  after the semicolon is usually a duplicate of the half before it. */
export function injuryDetail(row: {
  injury_type?: string | null;
  short_comment?: string | null;
}): string {
  const raw = row.injury_type ?? row.short_comment ?? "";
  const body = raw.replace(/^Injury\/Illness\s*-\s*/i, "");
  const [first, second] = body.split(";").map((part) => part.trim());
  if (!first) return second ?? "";
  if (second && second.toLowerCase() !== first.toLowerCase()) return `${first} · ${second}`;
  return first;
}
