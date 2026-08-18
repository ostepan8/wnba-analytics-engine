# Overnight improvement log

Autonomous overnight batch, run to run: implement in a worktree, verify
against the real production database and site, merge, push, deploy, verify
live, repeat. Scope for this batch was design/UX/stats-surfacing polish
only, frontend-only (one narrowly-scoped backend query permitted, mirroring
the existing `/teams/{id}/defense` pattern). `Model.tsx` and anything
auth/payments/ML/betting-shaped were off limits. Framing: make the free
experience around the paid `/model` tiers look like something worth
upgrading from — trustworthy, considered, complete.

Research pass before cycle 1 (a forked, read-only survey of
`IMPROVEMENT_LOG.md`, every page, `lib/api.ts` against every backend route
file, and recent git log) confirmed which pages had genuinely not been
touched in the prior 10-loop pass — League, Players, Teams, Research — and
surfaced concrete, unclaimed gaps in each, which is where all 5 cycles
below came from.

## Cycle 1: Rebounds, assists, steals and blocks on the Players list

**What changed**: `/players` (`analytics_repo.py`, `_PLAYERS` query) only
ever selected `points` and `minutes` out of `player_game_stats`, even
though rebounds/assists/steals/blocks live in the same table and the
`one_row_per_game` CTE already had the row in hand — extending the
`SELECT` was a same-shape addition, not new data collection.
`Players.tsx` already had the `SortTh`/`useSort` pattern built from an
earlier loop, so REB/AST/STL/BLK slotted in as four more sortable columns
rather than a new mechanism. This was `IMPROVEMENT_LOG.md`'s own
explicitly-flagged gap ("Players.tsx still can't sort by rebounds, assists,
steals or blocks... would need a backend change").

**Why**: A player known for defense or passing had no column that showed
it — points was the only lens the whole roster could be ranked through.

**Verification**: SQL sanity-checked read-only against the real production
database before shipping (10-row sample, sane averages). Lint and build
clean. Playwright against the pre-deploy build (proxied to prod API) showed
the new columns rendering as "—" as expected, since the old API had no such
fields yet — backend and frontend ship together in one image, so this is
the correct pre-deploy state, not a bug. Post-deploy: confirmed via direct
API curl and a live Playwright screenshot that real per-player averages
(A'ja Wilson 9.6 REB / 3.1 AST / 1.5 STL / 2.0 BLK, etc.) render correctly,
sortable, zero console errors.

**Status**: Shipped. Commit `d9cb7b4`, merged as `581e865`.

## Cycle 2: Real team colours on the All Teams grid

**What changed**: Every other team-identity surface (TeamDetail,
PlayerDetail, GameDetail) uses `Panel`'s `accent` stripe with the team's
real brand colour from `teamColors.ts`. The "All teams" card grid on
`Teams.tsx` hand-rolled its own `<article className="panel">` markup
instead of using the shared `Panel` component, so it was the one
team-identity surface in the app that still looked unstyled next to its
own standings table on the same page. Swapped the hand-rolled article for
`Panel accent={teamColor(row.abbreviation)}` — no layout change, since
`.panel__body`'s existing padding already matched the inline style it
replaced.

**Why**: Visual consistency the identity system was built for, applied to
the one place that had skipped it.

**Verification**: Lint and build clean. Playwright against real prod data
(proxied) showed all 15 team cards with correct, distinct brand-colour
accent stripes. Live post-deploy screenshot confirmed the same, zero
console errors.

**Status**: Shipped. Commit `a17150e`, merged as `0605e2d`.

## Cycle 3: Playoff race status and recent form on League's conference tables

**What changed**: `StandingRow` already carries `last10_wins`/`losses`,
`games_behind_playoff`, and the `clinched`/`eliminated`/
`in_playoff_position` fields the existing `RaceBadge` component reads —
`League.tsx` fetched all of it and rendered none of it, showing bare
W-L-PCT-GB next to a raw seed number on what is likely the site's
first-landing standings view. Added GB8 (league-wide games behind the
cut), L10, and the same `RaceBadge` status `Teams.tsx` already uses.

**Real bug found and fixed in the same cycle**: the two conference tables
sharing a `grid--2` row couldn't fit 10 columns without hiding the last
two behind horizontal scroll — confirmed via computed layout (`scrollWidth`
vs `clientWidth`), not just a screenshot guess. Root cause was CSS Grid's
default auto-minimum-size fighting `minmax()` track sizing; fixed generally
with `min-width: 0` on `.panel` (not League-specific — this was a latent
bug that could bite any panel-in-a-grid with wide content), and switched
the two conference tables from side-by-side to stacked full-width, since a
standings table is read top-to-bottom, not side-by-side, and 10 columns
need the room.

**Why**: League was the thinner of the two standings pages for the exact
same payload; a first-time visitor comparing the two would notice.

**Verification**: Lint and build clean both before and after the layout
fix. Playwright caught the overflow regression pre-deploy (this is exactly
what step 5 of the pipeline is for); re-verified after the fix showed every
column fitting cleanly with real production data (magic numbers,
clinched/eliminated badges, L10 records). Live post-deploy screenshot
confirmed the same, zero console errors.

**Status**: Shipped. Commit `6595324`, merged as `8bf604f`.

## Cycle 4: A real favicon

**What changed**: `frontend/` had no `public/` directory and `index.html`
linked no icon at all — every browser tab showed the generic blank-document
default. Added `frontend/public/favicon.svg` (a "W" monogram in the app's
own accent blue, `tokens.css` series-1) and linked it from `index.html`.
Used a plain system-sans fallback stack rather than the Big Shoulders
Display webfont, since a favicon can render before, or without, any page
fetch completing.

**Real bug found and fixed in the same cycle**: the first draft's SVG
comment referenced `--series-1` (a CSS custom property name) inside an XML
comment, and XML comments cannot contain `--` mid-comment — this made the
file invalid as a standalone XML document. Caught by trying to render it
directly rather than only checking it via `<img src>` (which is more
forgiving); fixed by rewording the comment.

**Why**: Small, but exactly the "looks unfinished" category this batch
targets — a paid product's browser tab looking identical to an empty
scratch file undercuts trust before a visitor reads a single number.

**Verification**: Lint and build clean; confirmed `favicon.svg` lands in
the build output root and is served with the correct `image/svg+xml`
content type both from the local preview and, post-deploy, from
`https://wnba.onephos.com/favicon.svg` directly. Rendered the icon inline
in a real page context at both 64px and 16px to confirm legibility at
actual favicon size. Zero console errors, before and after deploy.

**Status**: Shipped. Commit `087f916`, merged as `1cad834`.

## Cycle 5: Sort failing jobs first on the pipeline health grid

**What changed**: `/health/jobs` returns jobs in schedule order, so a
failing job sat wherever its name happened to fall alphabetically among a
dozen healthy ones on Research's job-health grid — the one thing that grid
exists to catch was the thing a reader had to scan for. Jobs now sort by
urgency (failing/timing out, then not-yet-run, then running, then healthy,
then disabled), stable within each tier so equally-urgent jobs keep
schedule order. Also surfaced `any_failing`'s underlying signal (the raw
field itself was fetched and never read) as a plain-language panel header
— "All enabled jobs healthy" or a count of what needs attention — computed
from the same per-job status the grid sorts by, so the answer is visible
before scanning a single row.

**Real bug found and fixed in the same cycle**: the first draft passed
`hint` to `Panel` without a `title`, and `Panel`'s header (where `hint`
renders) only mounts when `title` or `tools` is present — so the summary
silently never appeared. Caught by screenshotting the actual result rather
than trusting the diff; fixed by adding `title="Scheduled jobs"`.

**Why**: This is the page's own transparency mechanism for "is the data
current" — burying a failure alphabetically works against the page's
purpose.

**Verification**: Lint and build clean. Playwright against real prod data
confirmed pending jobs sort first, healthy jobs in the middle, the one
disabled job last, and the header correctly reads "All enabled jobs
healthy" when true. Live post-deploy screenshot confirmed the same
ordering and header against real job data, zero console errors.

**Status**: Shipped. Commit `ebf8499`, merged as `db30888`.

## Summary

5 of 5 cycles shipped, none abandoned. 5 feature commits + 5 merge commits
landed on `main` and deployed to production, each verified live before the
next cycle started. Two real bugs (a CSS Grid overflow and an invalid XML
comment, a Panel prop that silently no-oped) were caught by this pipeline's
own verification step before shipping, not after — worth noting as evidence
the pipeline is pulling its weight, not just ceremony.

**Left for a future batch**: GameDetail, Home, PlayerDetail and TeamDetail
were re-surveyed this batch and, unlike League/Players/Teams/Research,
didn't turn up a concrete unclaimed gap — worth a fresh look after this
batch's changes settle, but nothing was forced in just to hit a quota.
`/health` (the bare liveness probe) remains the one backend endpoint
confirmed genuinely unused by the frontend, and deliberately so.
