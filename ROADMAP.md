# Roadmap

An open, WNBA-only analytics engine: odds history, outcomes, and box-score/player
data joined together as a foundation for insights, picks, and visualizations.

This repo is the **data and analytics engine** — the open-source core. The
consumer-facing product built on top of it (subscriptions, alerts, premium
picks) is intentionally out of scope here and will live separately, so the
engine stays useful and inspectable on its own.

Scope is WNBA only, on purpose. No multi-sport expansion is planned until this
is solid.

---

## Phase 0 — Odds & outcomes foundation (done, private companion pipeline)

Not part of this repo yet, but the reason this project exists: four seasons of
WNBA historical odds (2022–present) across 32 sportsbooks, with line-movement
snapshots (T-7d / T-24h / T-1h / closing) rather than just a single closing
price, plus final scores for ~100% of completed games. Built as a separate
personal data-hoarding project against the-odds-api.com. Folding this into the
open engine (or publishing a derived, license-clean subset of it) is a later
decision, not a blocker for Phase 1.

## Phase 1 — Stats & box-score foundation (current focus)

The actual gap: odds + final score tells you who won, not *why*, and isn't
enough to build real insights on. This phase adds:

- Box scores and player-level stats (points, rebounds, assists, shooting
  splits, minutes) per game, backfilled 2022–present and swept going forward.
- Situational context: home/road, rest days, back-to-backs, pace.
- A clean join key back to existing odds/outcome data (team + date matching,
  same approach already proven for the ESPN score backfill).

Candidate sources: ESPN's public scoreboard/box-score endpoints (already have
a working, rate-limited puller pattern to extend) and balldontlie.io's WNBA
endpoints as a fallback/cross-check. Both are free; no new paid data contracts
needed for this phase.

Deliverable: a Postgres schema + sweeper pipeline that produces one queryable
dataset — odds, line movement, outcomes, and box scores — per game, per player.

## Phase 2 — Insights engine

Rules-based first, not ML: situational splits, player prop hit-rate trends,
line-movement-vs-outcome patterns, matchup history. Fast to build, easy to
explain, and doesn't require a trained model to be useful. ML-based modeling
is a later, explicit decision — not a default.

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
- ML-driven predictions before the rules-based insights layer (Phase 2) proves
  out on real data.
