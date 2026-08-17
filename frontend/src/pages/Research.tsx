import { useState } from "react";
import { Link } from "react-router-dom";
import { Async, Panel, Section, Stat } from "../components/ui";
import type { DivergenceObservation, DivergenceVenue, JobHealth, PropMarketRow } from "../lib/api";
import { propLabel, useQuery } from "../lib/api";
import { num, pct, relativeTime, shortDate, signed, timeOf } from "../lib/format";

const STATUS: Record<string, { color: string; icon: string; label: string }> = {
  ok: { color: "var(--good)", icon: "✓", label: "Healthy" },
  running: { color: "var(--series-1)", icon: "◍", label: "Running" },
  failed: { color: "var(--critical)", icon: "✕", label: "Failing" },
  timeout: { color: "var(--serious)", icon: "⧗", label: "Timing out" },
  pending: { color: "var(--warning)", icon: "◌", label: "Not yet run" },
  disabled: { color: "var(--ink-muted)", icon: "◻", label: "Disabled" },
};

function stateOf(job: JobHealth) {
  if (!job.enabled) return STATUS.disabled;
  if (!job.last_status) return STATUS.pending;
  return STATUS[job.last_status] ?? STATUS.failed;
}

export default function Research() {
  const [logOpen, setLogOpen] = useState(false);
  const divergence = useQuery<{ venues: DivergenceVenue[] }>("/divergences/summary");
  const health = useQuery<{ jobs: JobHealth[]; any_failing: boolean }>("/health/jobs");
  const props = useQuery<{ markets: PropMarketRow[] }>("/lines/props");
  // Only fetched once opened -- the aggregates above are the page's real
  // content; the itemized log is an audit trail for someone who wants to
  // check one row, not something to load unasked.
  const log = useQuery<{ divergences: DivergenceObservation[]; count: number }>(
    logOpen ? "/divergences?limit=30" : null,
  );

  return (
    <>
      <Section
        title="Cross-venue divergence"
        note="A forward experiment in progress, not a result."
      >
        <Panel>
          <p className="prose">
            Prediction markets and sportsbooks price the same game differently at the same moment.
            Whether that gap is <em>executable</em> cannot be settled by a backtest: historical
            sportsbook captures sit ~60 minutes apart and the move happens inside that window. So
            the prices are logged forward, at capture cadence, and graded afterwards.
          </p>
          <p className="prose" style={{ marginTop: "var(--s-3)" }}>
            Every rate below carries its denominator deliberately. Closing-line value reaches
            significance around 120 graded observations; return on investment needs closer to
            10,600. Reading a survival rate without its count is how a search this wide produces a
            confident answer to a question it has not yet earned.
          </p>
        </Panel>
      </Section>

      <Async query={divergence} empty={(data) => data.venues.length === 0}>
        {(data) => (
          <div className="grid grid--2">
            {data.venues.map((venue) => (
              <Panel key={venue.venue} title={venue.venue}>
                <div className="grid grid--3">
                  <Stat value={num(venue.observations)} label="Observations" />
                  <Stat
                    value={
                      venue.survival_checked
                        ? pct(venue.price_survived / venue.survival_checked)
                        : "—"
                    }
                    label="Price still there"
                    detail={`of ${num(venue.survival_checked)} checked`}
                  />
                  <Stat
                    value={venue.mean_clv ? signed(Number(venue.mean_clv) * 100, 2) + "%" : "—"}
                    label="Mean CLV"
                    detail={
                      venue.clv_graded < 120
                        ? `${venue.clv_graded} graded — under the ~120 needed`
                        : `${venue.clv_graded} graded`
                    }
                  />
                </div>
              </Panel>
            ))}
          </div>
        )}
      </Async>

      <Panel
        title="Individual observations"
        hint="the most recent 30, across venues"
        tools={
          <button
            type="button"
            className="control"
            aria-expanded={logOpen}
            onClick={() => setLogOpen((value) => !value)}
          >
            {logOpen ? "Hide log" : "Show log"}
          </button>
        }
        flush={logOpen}
      >
        {logOpen ? (
          <Async query={log} empty={(data) => data.divergences.length === 0}>
            {(data) => (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Captured</th>
                      <th>Game</th>
                      <th>Venue</th>
                      <th>Side</th>
                      <th>Edge</th>
                      <th>Price survived</th>
                      <th>CLV</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.divergences.map((row) => (
                      <tr key={row.id}>
                        <td>
                          {shortDate(row.observed_at)} {timeOf(row.observed_at)}
                        </td>
                        <td>
                          <Link to={`/games/${row.game_id}`}>
                            {row.away_abbr} @ {row.home_abbr}
                          </Link>
                        </td>
                        <td>{row.venue}</td>
                        <td>{row.side}</td>
                        <td>{pct(row.edge)}</td>
                        <td>
                          {row.price_survived === null ? (
                            <span className="muted">not checked</span>
                          ) : (
                            <span
                              className={row.price_survived ? "badge badge--good" : "badge badge--bad"}
                            >
                              {row.price_survived ? "still there" : "moved"}
                            </span>
                          )}
                        </td>
                        <td>{row.clv != null ? signed(Number(row.clv) * 100, 1) + "%" : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        ) : (
          <p className="prose">
            The aggregates above are the log's real content — every rate reported with its
            denominator, for the reasons in the panel above. This is the itemized version behind
            them, for auditing one observation at a time rather than reading a trend into it.
          </p>
        )}
      </Panel>

      <Section
        title="The unders bias"
        note="Real, well-documented, and not a strategy."
      >
        <Panel>
          <p className="prose" style={{ marginBottom: "var(--s-4)" }}>
            Overs lose in every prop market, across tens of thousands of graded closing lines.
            That is a genuine bias in how these numbers are set. It is also not money: graded at
            prices that could actually be taken, blanket under-betting returns −2.05% to −10.68%.
            The vig is larger than the edge, which is the single most common way a real pattern
            turns into a losing system.
          </p>
          <Async query={props} empty={(data) => data.markets.length === 0}>
            {(data) => (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Market</th>
                      <th>Graded</th>
                      <th>Avg line</th>
                      <th>Over</th>
                      <th>Under</th>
                      <th>Push</th>
                      <th>Over rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.markets.map((row) => {
                      const decided = row.overs + row.unders;
                      return (
                        <tr key={row.prop_type}>
                          <td>{propLabel(row.prop_type)}</td>
                          <td>{num(row.games)}</td>
                          <td>{row.avg_line ?? "—"}</td>
                          <td>{num(row.overs)}</td>
                          <td>{num(row.unders)}</td>
                          <td>{num(row.pushes)}</td>
                          <td>{decided ? pct(row.overs / decided) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        </Panel>
      </Section>

      <Section
        title="Pipeline"
        note="Every scheduled run is recorded, successes and failures alike."
      >
        <Panel>
          <p className="prose" style={{ marginBottom: "var(--s-4)" }}>
            The engine's real failure mode is not a crash — it is jobs quietly not running while
            every page above keeps rendering week-old numbers as though they were current. Data
            freshness cannot detect that either: the off-season looks identical to a dead
            scheduler. Only a record of job <em>execution</em> separates them.
          </p>
          <Async query={health} empty={(data) => data.jobs.length === 0}>
            {(data) => (
              <div className="grid grid--3">
                {data.jobs.map((job) => {
                  const state = stateOf(job);
                  return (
                    <div key={job.job_name} style={{ display: "flex", gap: "var(--s-2)" }}>
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: state.color,
                          marginTop: 7,
                          flex: "none",
                        }}
                      />
                      <div style={{ minWidth: 0 }}>
                        <div
                          style={{ fontSize: "var(--t-sm)", fontWeight: 560 }}
                          title={job.description || undefined}
                        >
                          {job.job_name}
                        </div>
                        <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-muted)" }}>
                          <span style={{ color: state.color, fontWeight: 620 }}>
                            {state.icon} {state.label}
                          </span>
                          {job.enabled && ` · ${relativeTime(job.last_success_at)}`}
                        </div>
                        {job.enabled && job.runs_24h != null && (
                          <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-muted)" }}>
                            {job.runs_24h} run{job.runs_24h === 1 ? "" : "s"} in 24h
                            {!!job.failures_24h && (
                              <span style={{ color: "var(--critical)" }}>
                                {" "}
                                · {job.failures_24h} failed
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Async>
        </Panel>
      </Section>
    </>
  );
}
