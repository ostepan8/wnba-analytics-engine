/* What a team is missing, in minutes and production.
 *
 * The injury report names people; it does not say what they were doing. "Three
 * out" is the same headline whether it is three end-of-bench players or a
 * 34-minute leading scorer plus two starters, and only one of those moves a
 * total. So every absence is shown with the per-game production it removes.
 *
 * The at-risk row is the one most pages throw away. A questionable 30-minute
 * starter is a bigger swing than a ruled-out reserve precisely because it is
 * unresolved while the number is being set — so it gets its own line rather
 * than being folded into "out" or dropped.
 *
 * Descriptive only: what a missing player averaged is a statement about what
 * has been removed, not a forecast of what her team will now score.
 */

import { Link } from "react-router-dom";
import type { AbsenceBucket, MatchupSide } from "../lib/api";
import { badgeClass, sourceLabel } from "../lib/injury";
import { pct } from "../lib/format";

function Line({
  label,
  bucket,
  tone,
}: {
  label: string;
  bucket: AbsenceBucket;
  tone: "bad" | "warn" | "good";
}) {
  if (bucket.count === 0) return null;
  const share = bucket.share_of_points;
  return (
    <div style={{ marginBottom: "var(--s-3)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--s-2)",
          marginBottom: "var(--s-1)",
        }}
      >
        <span className={`badge badge--${tone}`}>{label}</span>
        <span className="num" style={{ fontWeight: 620 }}>
          {bucket.minutes} min
        </span>
        <span className="num" style={{ fontWeight: 620 }}>
          {bucket.points} pts
        </span>
        {share != null && (
          <span className="muted" style={{ fontSize: "var(--t-xs)" }}>
            {pct(share, 0)} of the scoring
          </span>
        )}
      </div>
      <ul style={{ display: "grid", gap: 2, paddingLeft: "var(--s-2)" }}>
        {bucket.players.map((player) => (
          <li
            key={player.player_id}
            style={{ display: "flex", gap: "var(--s-2)", fontSize: "var(--t-sm)" }}
          >
            <span
              className={badgeClass(player.status)}
              style={{ flex: "none" }}
              title={sourceLabel(player.source) ?? undefined}
            >
              {player.status}
            </span>
            <Link to={`/players/${player.player_id}`}>{player.full_name}</Link>
            <span className="num muted" style={{ marginLeft: "auto", fontSize: "var(--t-xs)" }}>
              {player.games_played === 0
                ? "no games"
                : `${player.minutes ?? "—"} min · ${player.points ?? "—"} pts · ${player.rebounds ?? "—"} reb · ${player.assists ?? "—"} ast`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Absences({ side, label }: { side: MatchupSide; label: string }) {
  const absences = side.absences;
  if (!absences) return null;
  const anything = absences.out.count + absences.at_risk.count + absences.likely.count;

  return (
    <div>
      <h5 style={{ fontSize: "var(--t-sm)", fontWeight: 620, marginBottom: "var(--s-2)" }}>
        {label}
      </h5>
      {anything === 0 ? (
        <p className="muted" style={{ fontSize: "var(--t-sm)" }}>
          Nobody listed.
        </p>
      ) : (
        <>
          <Line label="Out" bucket={absences.out} tone="bad" />
          <Line label="At risk" bucket={absences.at_risk} tone="warn" />
          <Line label="Expected to play" bucket={absences.likely} tone="good" />
        </>
      )}
    </div>
  );
}
