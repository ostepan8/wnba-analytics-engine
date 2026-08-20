---
name: frontend-app
description: Map of frontend/ -- the Vite + React 19 + TypeScript SPA. Data-fetching pattern (hand-rolled useQuery, no state library), routing, component/chart reuse conventions, and known gotchas. Load when adding or fixing a page, component, or chart, or wiring up a new backend field.
---

# Frontend app

A single-page React 19 + TypeScript app built with Vite, `react-router-dom`
v7 for routing. **No state-management library, no CSS framework, no
charting library** -- data fetching is a hand-rolled `useQuery` hook
against same-origin `/api/*`, and every chart is hand-built inline SVG.
The whole product is explicitly read-only/informational (footer: "read-only
· price ingestion only, never order placement"). See [[runtime-services]]
for the FastAPI backend this talks to, and [[parallel-worktree-lifecycle]]
before editing.

## Structure

| Directory | Contents |
|---|---|
| `frontend/src/pages/` | One file per route (11 pages: Home, Games, GameDetail, League, Model, Players, PlayerDetail, Teams, TeamDetail, Research, NotFound) |
| `frontend/src/components/` | Reusable building blocks (`GamePanel`, `Matchup`, `Absences`, etc.) plus the shared primitive set in `ui.tsx` |
| `frontend/src/charts/` | Hand-built SVG charts sharing `primitives.tsx` (`ChartFrame`, `useTooltip`, `TimeSeries`, `BarList`) |
| `frontend/src/lib/` | `api.ts` (fetching + every response type), `format.ts`, `injury.ts`, `teamColors.ts`, `useSort.ts` |
| `frontend/src/styles/` | `tokens.css` (single source of truth for color/spacing/radius/type) + `global.css` |

## Data fetching -- the only pattern

`useQuery<T>(path)` in `lib/api.ts` is the **only** data-access pattern
app-wide. It fetches on mount and on `path` change, aborts the in-flight
request on unmount/path-change via `AbortController` (prevents races on
fast navigation), and exposes `{data, error, loading, refetch}`.
Components branch on that through the shared `<Async>` render-prop
component in `ui.tsx` -- loading/error/empty/success states standardized
once. `useQuery` also guards against React StrictMode's double-invoke
firing duplicate real requests via a `latest` ref. Local UI state (search,
season picker, sort column) is plain `useState`/`useMemo` per component --
no global store, no Redux/Zustand/react-query.

`lib/api.ts` also defines `ASSETS`/`teamLogo`/`playerImage`, which point
directly at an external S3 bucket (`https://s3.onephos.com/wnba-assets`)
-- images are **not** proxied through the API.

## Routing and layout

`App.tsx` declares every route centrally (`<Routes>`/`<Route>`), nested
detail routes use `:id` params read via `useParams`
(`/teams/:teamId`, `/players/:playerId`, `/games/:gameId`). It also owns
the nav bar, light/dark/system theme toggle (`data-theme` + localStorage),
and scroll-to-top on navigate. `ErrorBoundary.tsx` wraps **only** the
routed `<main>` content, deliberately not the nav, so a broken page still
lets the user navigate away; it resets on route change via a `resetKey`
prop.

**All data paths must go under `/api`.** Without the prefix, a client-side
route like `/players/36` previously collided with a backend endpoint of
the same shape, and navigating rendered raw JSON instead of the page. The
FastAPI backend registers routers before the SPA static mount specifically
so route-matching wins (see [[runtime-services]]).

## Reuse discipline

`components/ui.tsx` (`Panel`, `Section`, `Stat`, `Async`, `TeamLogo`,
`PlayerAvatar`, `SortTh`, `RaceBadge`, etc.) is the shared vocabulary every
page composes from -- its own header comment states "none of them
restyles another." This is enforced by convention, not lint; keep it that
way when adding new UI. `styles/tokens.css` is the only place a raw hex or
magic pixel value should exist; a CVD-validated categorical/diverging
chart palette also lives there -- don't substitute chart hues without
re-validating contrast.

`components/LazySection.tsx` uses an `IntersectionObserver` to defer
mounting (and therefore fetching) off-screen sections -- critical on
`Home`, where a day of 5 games × 6 tabs each would otherwise fire 30
concurrent requests; `GamePanel` is collapsed-by-default with per-tab
fetch-on-open for the same reason.

`lib/useSort.ts` is a generic client-side sort hook, explicitly documented
as valid only for already-fully-loaded (non-paginated) tables.

## Gotchas

- The `lint` script is actually just `tsc -b --noEmit` (type-checking),
  not an eslint pass.
- `ScrollToTop`'s effect has a documented caveat: `scrollTo`'s return
  value is not a function, so returning it directly from a `useEffect`
  would throw "destroy is not a function" on cleanup -- this incident is
  what motivated adding `ErrorBoundary` in the first place.
- Before assuming new backend work is needed for a "missing" field, grep
  every `Row`/`Response` interface in `api.ts` against its page's JSX --
  `IMPROVEMENT_LOG.md` and `OVERNIGHT_LOG.md` both record that most gaps
  found were already-fetched-but-unrendered fields, not missing endpoints.
- `/health` is the one backend endpoint deliberately unused by the
  frontend.
- **`Model.tsx` and anything auth/payments/ML/betting-shaped are
  off-limits for casual edits** -- explicitly called out in the recent
  autonomous-improvement logs as sensitive/out of scope.

## Stack

react 19.2, react-dom 19.2, react-router-dom 7.9.3 -- the entire runtime
dependency list (no UI kit, no chart lib, no state lib, no HTTP client
beyond native `fetch`). Dev: vite 7.1.9, typescript 5.9.3. `npm run build`
is `tsc -b && vite build`; the FastAPI backend serves the built output
statically (same-origin by design -- no CORS config, no configurable base
URL in the frontend).
