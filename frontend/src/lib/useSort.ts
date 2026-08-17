/* Client-side sort for a table that is already fully loaded on screen.
 *
 * Not for anything paginated server-side -- sorting a page of 25 out of 400
 * rows would silently lie about the full ranking. Everywhere this is used so
 * far (Players, a team roster) fetches its whole list in one call already. */

import { useMemo, useState } from "react";

export type SortDirection = "asc" | "desc";

interface SortState<K extends string> {
  key: K | null;
  direction: SortDirection;
}

/** Numeric-looking strings sort numerically, not lexicographically. The API
 *  returns most per-game averages as strings (to keep a trailing zero like
 *  "18.0"), and string-sorting would put "9.0" after "10.0". Nulls sort last
 *  in either direction -- "no data" is not the same claim as "zero". */
function compareValues(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const an = Number(a);
  const bn = Number(b);
  if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
  return String(a).localeCompare(String(b));
}

export function useSort<T, K extends string>(
  rows: T[],
  accessor: (row: T, key: K) => unknown,
  initial?: K,
) {
  const [state, setState] = useState<SortState<K>>({ key: initial ?? null, direction: "desc" });

  const sorted = useMemo(() => {
    if (!state.key) return rows;
    const key = state.key;
    const copy = [...rows].sort((a, b) => compareValues(accessor(a, key), accessor(b, key)));
    return state.direction === "asc" ? copy : copy.reverse();
  }, [rows, state, accessor]);

  function toggleSort(key: K) {
    // A fresh column always opens descending -- "biggest first" is what a
    // reader wants from PTS or MIN, and flipping only makes sense once they
    // are already looking at the column they asked for.
    setState((previous) =>
      previous.key === key
        ? { key, direction: previous.direction === "desc" ? "asc" : "desc" }
        : { key, direction: "desc" },
    );
  }

  return { sorted, sortKey: state.key, direction: state.direction, toggleSort };
}
