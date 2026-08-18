/* The paid tier.
 *
 * What is sold here is ACCESS -- to the full dataset, the raw feeds, and the
 * research as it develops. Not picks, and not a claimed edge.
 *
 * That framing is not marketing caution, it is what the project's own
 * MODELING_FINDINGS.md supports: "No FORECASTING edge has been produced from
 * this data." One strategy has survived every control, and it is measured in
 * closing-line value with realised ROI explicitly described as statistically
 * silent -- ~700 observations against the ~10,600 needed. Selling that as a
 * winning system would be selling something the repository documents as absent,
 * and ROADMAP.md's non-goals put this project on the information side of that
 * line on purpose.
 *
 * So the page states the evidence plainly, including the parts that argue
 * against buying, and sells the data instead.
 */

import { useState } from "react";
import { Async, Panel, Section, Stat } from "../components/ui";
import type { DatasetSummary } from "../lib/api";
import { useQuery } from "../lib/api";
import { num } from "../lib/format";

const TIERS = [
  {
    id: "free",
    name: "Open",
    price: "Free",
    cadence: "forever",
    blurb: "Everything on this site, and the read API behind it.",
    features: [
      "Standings, box scores, shot charts",
      "Play-by-play score flow",
      "Public read API + OpenAPI docs",
      "Cross-venue research summary",
    ],
    cta: null,
  },
  {
    id: "data",
    name: "Data",
    price: "$19",
    cadence: "per month",
    blurb: "The whole dataset, not just what a page renders.",
    features: [
      "Full history export (Postgres dump or Parquet)",
      "Raw prediction-market captures",
      "Per-game sportsbook line movement",
      "Higher API rate limits",
    ],
    cta: "Subscribe",
    highlight: true,
  },
  {
    id: "research",
    name: "Research",
    price: "$79",
    cadence: "per month",
    blurb: "The divergence experiment as it runs, with its working shown.",
    features: [
      "Live divergence log with grading",
      "Methodology notes and negative results",
      "Feature pipeline with point-in-time guards",
      "Direct access for questions",
    ],
    cta: "Subscribe",
  },
];

export default function Model() {
  const summary = useQuery<DatasetSummary>("/summary");
  const [pending, setPending] = useState<string | null>(null);

  /* Checkout is a server concern: the price and the session are created by the
     API from a secret key, never by the browser, or anyone could name their own
     price. This posts and follows the redirect the server hands back. */
  async function startCheckout(tier: string) {
    setPending(tier);
    try {
      const response = await fetch("/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      if (!response.ok) throw new Error(`checkout unavailable (${response.status})`);
      const { url } = (await response.json()) as { url: string };
      window.location.href = url;
    } catch (error) {
      setPending(null);
      alert(
        `Checkout is not connected yet: ${(error as Error).message}\n\n` +
          "Stripe keys have not been configured on the server.",
      );
    }
  }

  return (
    <>
      <Section
        title="Access the full dataset"
        note="What is sold is the data, not a prediction."
        level="h1"
      >
        <Panel>
          <p className="prose">
            This project has run well over 200 hypothesis tests across 126 features, four prop
            markets and two venues. At that count roughly ten results with <code>|t|</code> &gt; 2
            are expected from noise alone, so the bar here is <code>|t|</code> ≈ 3.5 — and{" "}
            <strong>exactly one result clears it</strong>: sportsbooks and prediction markets
            disagree often enough to be worth about +0.97 points of closing-line value, replicated
            independently on Polymarket (t = +7.77) and Kalshi (t = +8.28).
          </p>
          <p className="prose" style={{ marginTop: "var(--s-3)" }}>
            That is a real finding and it is <em>not</em> a product. No forecasting edge has been
            produced from this data: nothing here predicts a game or a stat line better than the
            closing price does. Realised return on the one surviving strategy is statistically
            silent — detecting an edge that small needs roughly 10,600 graded bets, and the log
            holds a few hundred. Anyone selling you picks off numbers like these is selling you
            variance.
          </p>
          <p className="prose" style={{ marginTop: "var(--s-3)" }}>
            So the subscription buys the <strong>dataset and the working</strong>: every capture,
            every negative result, and the experiment as it accumulates. Draw your own conclusions
            — that is the point.
          </p>
        </Panel>
      </Section>

      <Async query={summary}>
        {(data) => (
          <Panel title="What you get access to">
            <div className="grid grid--4">
              <Stat value={num(data.games)} label="Games" />
              <Stat value={num(data.market_price_snapshots)} label="Price snapshots" />
              <Stat value={num(data.sportsbook_game_odds)} label="Sportsbook rows" />
              <Stat value={num(data.divergence_observations)} label="Logged divergences" />
            </div>
          </Panel>
        )}
      </Async>

      <Section title="Plans">
        <div className="grid grid--3">
          {TIERS.map((tier) => (
            <article
              key={tier.id}
              className="panel"
              style={{
                padding: "var(--s-5)",
                borderColor: tier.highlight ? "var(--accent)" : undefined,
              }}
            >
              <header style={{ marginBottom: "var(--s-3)" }}>
                <h3 style={{ fontSize: "var(--t-lg)", fontWeight: 640 }}>{tier.name}</h3>
                <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s-2)" }}>
                  <span
                    className="num"
                    style={{ fontSize: "var(--t-2xl)", fontWeight: 620, letterSpacing: "-0.03em" }}
                  >
                    {tier.price}
                  </span>
                  <span className="muted" style={{ fontSize: "var(--t-xs)" }}>
                    {tier.cadence}
                  </span>
                </div>
                <p className="prose" style={{ marginTop: "var(--s-2)" }}>
                  {tier.blurb}
                </p>
              </header>

              <ul style={{ display: "grid", gap: "var(--s-2)", marginBottom: "var(--s-4)" }}>
                {tier.features.map((feature) => (
                  <li
                    key={feature}
                    style={{ fontSize: "var(--t-sm)", display: "flex", gap: "var(--s-2)" }}
                  >
                    <span style={{ color: "var(--good)" }}>✓</span>
                    {feature}
                  </li>
                ))}
              </ul>

              {tier.cta ? (
                <button
                  className="control"
                  style={{
                    width: "100%",
                    justifyContent: "center",
                    height: 38,
                    background: tier.highlight ? "var(--accent)" : undefined,
                    color: tier.highlight ? "var(--ink-inverse)" : undefined,
                    borderColor: tier.highlight ? "var(--accent)" : undefined,
                  }}
                  disabled={pending !== null}
                  onClick={() => startCheckout(tier.id)}
                >
                  {pending === tier.id ? "Redirecting…" : tier.cta}
                </button>
              ) : (
                <span className="muted" style={{ fontSize: "var(--t-sm)" }}>
                  You are using this now.
                </span>
              )}
            </article>
          ))}
        </div>
      </Section>

      <Panel title="Before you subscribe">
        <ul className="prose" style={{ display: "grid", gap: "var(--s-2)" }}>
          <li>
            <strong>Availability is best-effort.</strong> This runs on self-hosted hardware behind a
            home internet connection. There is no uptime guarantee.
          </li>
          <li>
            <strong>Nothing here places bets.</strong> Prediction-market integration is read-only
            price ingestion. There is no order placement anywhere in this system.
          </li>
          <li>
            <strong>The sportsbook feed is currently stale.</strong> Its upstream API key lapsed;
            live odds resume when that is restored. Prediction-market and box-score data are
            current.
          </li>
        </ul>
      </Panel>
    </>
  );
}
