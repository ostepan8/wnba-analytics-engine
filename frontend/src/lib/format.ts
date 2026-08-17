/* Formatting. Centralised so a number never renders two different ways in two
   places -- the small inconsistency that makes an interface feel unfinished. */

const numberFormat = new Intl.NumberFormat("en-US");

export const num = (value: number | string | null | undefined) =>
  value == null ? "—" : numberFormat.format(Number(value));

/** One decimal, for per-game averages. */
export const avg = (value: number | string | null | undefined) =>
  value == null ? "—" : Number(value).toFixed(1);

export const pct = (value: number | string | null | undefined, digits = 1) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;

/** Basketball convention: .482, not 0.482 or 48.2%. */
export const rate = (value: number | string | null | undefined) =>
  value == null ? "—" : Number(value).toFixed(3).replace(/^0/, "");

export const signed = (value: number | string | null | undefined, digits = 0) => {
  if (value == null) return "—";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;
};

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });

export const timeOf = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** "12-4" shooting line, the way a box score prints it. */
export const madeAttempted = (made: number | null, attempted: number | null) =>
  made == null || attempted == null ? "—" : `${made}-${attempted}`;

/** American odds → implied probability, vig included. */
export const impliedFromAmerican = (odds: number | null | undefined) =>
  odds == null ? null : odds > 0 ? 100 / (odds + 100) : -odds / (-odds + 100);

export const CURRENT_SEASON = new Date().getUTCFullYear();

export const seasonOptions = (count = 5) =>
  Array.from({ length: count }, (_, index) => CURRENT_SEASON - index);
