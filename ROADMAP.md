# Roadmap

An open, WNBA-only analytics engine: odds history, outcomes, and box-score/player
data joined together as a foundation for insights, picks, and visualizations.

This repo is the **data and analytics engine** — the open-source core. The
consumer-facing product built on top of it (subscriptions, alerts, premium
picks) is intentionally out of scope here and will live separately, so the
engine stays useful and inspectable on its own.

Scope is WNBA only, on purpose. No multi-sport expansion is planned until this
is solid.

## Data strategy: why multiple sources

A single data source is replicable — anyone can point a script at the same
API we use. The actual moat is breadth: independently observing the same
games through box scores, sportsbook odds, *and* regulated prediction
markets means the edge doesn't collapse when one vendor changes an endpoint,
rate-limits us, or a competitor scrapes the same site we do. Different
sources also disagree in informative ways — e.g. a regulated exchange's
implied probability drifting from sportsbook consensus is itself a signal,
not just redundant coverage. Phase 2's insights are only as good as the
number of independent angles feeding them.

This means Phase 1 isn't "pick one box-score API," it's building the
**foundation to onboard many sources without a rewrite each time**: one
canonical schema, one adapter per provider, and a crosswalk table that
resolves each provider's own team/player/game IDs to ours.

---

## Phase 0 — Odds & outcomes foundation (done, private companion pipeline)

Not part of this repo yet, but the reason this project exists: four seasons of
WNBA historical odds (2022–present) across 32 sportsbooks, with line-movement
snapshots (T-7d / T-24h / T-1h / closing) rather than just a single closing
price, plus final scores for ~100% of completed games. Built as a separate
personal data-hoarding project against the-odds-api.com. Folding this into the
open engine (or publishing a derived, license-clean subset of it) is a later
decision, not a blocker for Phase 1.

## Phase 1 — Multi-source data foundation (current focus)

The actual gap: odds + final score tells you who won, not *why*, and isn't
enough to build real insights on. This phase adds box scores, player-level
stats, and situational context — and, because breadth is the moat, the
architecture to keep adding independent sources cheaply:

- Box scores and player-level stats (points, rebounds, assists, shooting
  splits, minutes) per game, backfilled 2022–present and swept going forward.
- Situational context: home/road, rest days, back-to-backs, pace.
- Regulated prediction-market prices (Kalshi, Polymarket) captured
  alongside sportsbook odds — a second, independently-priced probability
  signal to diff against sportsbook consensus. **Read-only market-data
  ingestion only** — see Non-goals.
- A canonical schema (our own team/player/game IDs), one adapter per
  provider mapping raw → canonical, a crosswalk table resolving each
  provider's external IDs to ours, and precedence rules for when sources
  disagree (e.g. the-odds-api already wins over ESPN for final scores).

Provider list (free unless noted):

| Source | Category | Provides | Status |
|---|---|---|---|
| the-odds-api | Sportsbook odds | 32-book lines, line movement | Integrated (Phase 0, paid) |
| ESPN scoreboard/summary | Box score | Team + per-player box score | Priority add (unofficial) |
| stats.wnba.com | Advanced stats | Advanced box score, four factors, hustle, shot charts | Priority add (unofficial, richer than ESPN) |
| Kalshi | Prediction market | Per-game, prop, and futures market prices | Priority add (CFTC-regulated, free read) |
| Polymarket | Prediction market | Futures/award market prices | Priority add (free) |
| Basketball-Reference / Her Hoop Stats | Historical/advanced | Deep historical + advanced metrics | Secondary (scrape, no API) |
| balldontlie.io | Box score | Backup/cross-check | Secondary (free tier, depth unverified) |

Deliverable: a Postgres schema + adapter pipeline that produces one queryable
dataset — odds, line movement, prediction-market prices, outcomes, and box
scores — per game, per player, sourced from multiple independent providers.

## Phase 2 — Insights engine

Rules-based first, not ML: situational splits, player prop hit-rate trends,
line-movement-vs-outcome patterns, matchup history, and — enabled by Phase 1's
multi-source foundation — divergence between sportsbook consensus and
regulated prediction-market pricing (Kalshi/Polymarket vs the-odds-api).
Cross-source disagreement is a distinct signal from any single-source trend
and harder for a single-source competitor to replicate. Fast to build, easy
to explain, and doesn't require a trained model to be useful. ML-based
modeling is a later, explicit decision — not a default.

## Phase 3 — Picks + a public track record

Publish predictions transparently, graded against closing line and final
result, before anything is paywalled. A new product has no credibility yet;
an honest public track record — even a mediocre one at first — builds more
trust than any launch copy. This phase is where the engine starts feeding a
real product surface, likely in a separate repo.

## Phase 4 — Visualization / dashboard

Line-movement charts, player/team trend dashboards, prop hit-rate views. This
is where "deep analytics" becomes visible rather than just computed.

## Phase 5 — SaaS packaging (private, not part of this repo)

Free tier (public insights + track record) to build trust and traffic, paid
tier (full analytics, alerts, deeper history) to monetize. Auth + billing.
Lives in a separate, closed product repo that consumes this engine.

## Phase 6 — Distribution

WNBA-specific bettor/fan communities are far less saturated with tooling than
NFL/NBA — that's the actual advantage of staying WNBA-only. Distribution plan
gets written once Phase 3's track record exists to point to.

---

## Non-goals (for now)

- Multi-sport support.
- Facilitating or placing bets, handling wagered money, or anything that
  crosses into money-transmission/gambling-license territory. This project is
  information and tooling, never the sportsbook.
- Trading on Kalshi, Polymarket, or any exchange. Prediction-market
  integration is **read-only price/probability ingestion for analysis**, not
  order placement, execution, or a trading bot. Same boundary as the
  sportsbook non-goal above, applied to exchanges.
- ML-driven predictions before the rules-based insights layer (Phase 2) proves
  out on real data.
