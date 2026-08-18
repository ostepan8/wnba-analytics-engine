/** Each team's real primary brand colour, keyed by abbreviation.
 *
 * Approximate, not sampled from a brand guide -- close enough to read as
 * "that team" without claiming to be an official swatch. Used only as a thin
 * accent (a stripe, a wash, a chip), never as body text colour or a full
 * background, so an approximation a shade off never costs legibility.
 *
 * Deliberately separate from the validated categorical palette in tokens.css:
 * that palette encodes MEANING (series 1 is always series 1, on every chart).
 * A team colour encodes IDENTITY instead, and only appears where a page is
 * already about that one team, so the two systems never compete for the same
 * pixel.
 */
const TEAM_COLORS: Record<string, string> = {
  ATL: "#e31837",
  CHI: "#418fde",
  CON: "#e03c31",
  DAL: "#0c2340",
  GS: "#79274c",
  IND: "#e03a3e",
  LA: "#552583",
  LV: "#c8102e",
  MIN: "#236192",
  NY: "#6ecdb2",
  PHX: "#3c1053",
  POR: "#e4002b",
  SEA: "#2c5234",
  TOR: "#4b2e83",
  WSH: "#e03a3e",
};

/** Falls back to the app's own accent so an unmapped or future team still
 *  reads as intentional rather than unstyled. */
export function teamColor(abbreviation: string | null | undefined): string {
  if (!abbreviation) return "var(--accent)";
  return TEAM_COLORS[abbreviation.toUpperCase()] ?? "var(--accent)";
}
