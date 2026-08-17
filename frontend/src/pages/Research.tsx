import { Async, Panel, Section, Stat } from "../components/ui";
import type { DivergenceVenue, JobHealth } from "../lib/api";
import { useQuery } from "../lib/api";
import { num, pct, relativeTime, signed } from "../lib/format";

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
  const divergence = useQuery<{ venues: DivergenceVenue[] }>("/divergences/summary");
  const health = useQuery<{ jobs: JobHealth[]; any_failing: boolean }>("/health/jobs");

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
                        <div style={{ fontSize: "var(--t-sm)", fontWeight: 560 }}>
                          {job.job_name}
                        </div>
                        <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-muted)" }}>
                          <span style={{ color: state.color, fontWeight: 620 }}>
                            {state.icon} {state.label}
                          </span>
                          {job.enabled && ` · ${relativeTime(job.last_success_at)}`}
                        </div>
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
