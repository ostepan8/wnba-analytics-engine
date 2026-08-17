/* The day's props where the live price and the recent frequency disagree most.
 *
 * A slate carries a few hundred priced props. Showing all of them is the same
 * as showing none, so this is the ordering that is about the data rather than
 * about alphabetical accident: biggest disagreement first, in either direction.
 *
 * The gap is not an edge and the copy below says so. It is the difference
 * between what a prediction market charges for the over and how often the
 * player has actually cleared that number in her last ten — two descriptions of
 * the same player, which can differ for reasons a frequency cannot see.
 */

import { Link } from "react-router-dom";
import { PlayerCell } from "./ui";
import type { SlateResponse, SlateTrend } from "../lib/api";
import { propLabel } from "../lib/api";
import { pct } from "../lib/format";

function Gap({ value }: { value: number }) {
  const above = value > 0;
  return (
    <span className={above ? "badge badge--good" : "badge badge--bad"}>
      {above ? "+" : "−"}
      {pct(Math.abs(value), 0)}
    </span>
  );
}

function Streak({ streak }: { streak: SlateTrend["streak"] }) {
  if (!streak || streak.length < 2) return <span className="muted">—</span>;
  return (
    <span className={streak.direction === "over" ? "badge badge--good" : "badge badge--bad"}>
      {streak.length} {streak.direction}
    </span>
  );
}

/** How the whole board leans.
 *
 * A top-twelve list where every gap points the same way reads as twelve
 * findings and is usually one — threshold contracts priced conservatively, or a
 * recent-form window running hot across the league. Saying so up front is the
 * difference between a reader seeing an ordering and a reader seeing a pattern.
 */
function Lean({ balance }: { balance: SlateResponse["balance"] }) {
  if (balance.rankable === 0) return null;
  const lopsided = balance.above === balance.rankable || balance.below === balance.rankable;
  return (
    <p className="prose" style={{ marginBottom: "var(--s-3)" }}>
      Of {balance.rankable} props on this slate with a live price and a full window,{" "}
      {balance.above} clear their line more often than the market charges and {balance.below} do
      so less often
      {balance.median_gap != null && <> — the middle of the board sits at {pct(balance.median_gap, 0)}</>}.
      {lopsided && (
        <>
          {" "}
          <strong>Every one leans the same way</strong>, which is a property of how this venue
          prices these contracts rather than {balance.rankable} separate findings.
        </>
      )}
    </p>
  );
}

export default function SlateTrends({
  trends,
  balance,
  ruledOut = 0,
}: {
  trends: SlateTrend[];
  balance: SlateResponse["balance"];
  /** Priced props belonging to players who are out, excluded from the ranking. */
  ruledOut?: number;
}) {
  if (trends.length === 0) {
    return (
      <p className="empty">
        No props on this slate have both a live price and ten decided games behind them.
        <br />
        <span style={{ fontSize: "var(--t-xs)" }}>
          The prediction-market feeds price a game closer to tip; a slate this far out is
          usually empty rather than broken.
        </span>
      </p>
    );
  }

  return (
    <>
      <Lean balance={balance} />
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th className="name">Player</th>
              <th>Market</th>
              <th>Line</th>
              <th title="What the market charges for the over right now">Price</th>
              <th title="How often she has cleared this line in her last ten">L10</th>
              <th title="Season-long, for the bigger sample">Season</th>
              <th title="Consecutive overs or unders, most recent first">Run</th>
              <th title="L10 rate minus the market price">Gap</th>
              <th>Game</th>
            </tr>
          </thead>
          <tbody>
            {trends.map((row) => (
              <tr key={`${row.game_id}-${row.player_id}-${row.prop_type}-${row.line}`}>
                <td className="name">
                  <PlayerCell playerId={row.player_id} name={row.full_name} />
                </td>
                <td>{propLabel(row.prop_type)}</td>
                <td className="num">o{row.line}</td>
                <td className="num">
                  {row.over_probability == null ? "—" : pct(row.over_probability, 0)}
                </td>
                <td className="num">
                  {row.l10.overs}/{row.l10.overs + row.l10.unders}
                  <br />
                  <span className="muted" style={{ fontSize: "var(--t-xs)" }}>
                    {row.l10.rate == null ? "" : pct(row.l10.rate, 0)}
                  </span>
                </td>
                <td className="num">
                  {row.season ? `${row.season.overs}/${row.season.overs + row.season.unders}` : "—"}
                  <br />
                  <span className="muted" style={{ fontSize: "var(--t-xs)" }}>
                    {row.season?.rate == null ? "" : pct(row.season.rate, 0)}
                  </span>
                </td>
                <td>
                  <Streak streak={row.streak} />
                </td>
                <td>
                  <Gap value={row.gap} />
                </td>
                <td>
                  <Link to={`/games/${row.game_id}`}>open</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="prose" style={{ marginTop: "var(--s-3)" }}>
        Gap is the last-ten hit rate minus what the market charges for the over. It is a
        disagreement between two descriptions, not an edge — a frequency cannot see a rotation
        change or a blowout, and ten games is ten games. Rows need a live price and at least six
        decided games to appear at all.
        {ruledOut > 0 && (
          <>
            {" "}
            {ruledOut} priced {ruledOut === 1 ? "prop" : "props"}{" "}
            {ruledOut === 1 ? "belongs" : "belong"} to a player who has been ruled out and{" "}
            {ruledOut === 1 ? "is" : "are"} excluded: the venues price a scratched player's over
            near zero, so those are the largest gaps on the board and every one of them is
            meaningless.
          </>
        )}
      </p>
    </>
  );
}
