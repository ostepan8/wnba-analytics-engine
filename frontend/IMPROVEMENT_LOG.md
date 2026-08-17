# Frontend improvement log

Ten planned loops over the 11 pages in `frontend/src/pages/` plus the shared
`components/` and `lib/`. This agent ran loops 1-5. A second agent picks up
6-10 by reading this file plus the "State for next agent" section at the
bottom.

## Loop 1: Wire matchup context into GameDetail

Pages/files touched: `frontend/src/pages/GameDetail.tsx`

What changed (UX): The standalone `/games/:id` page only had score flow, win
probability, sportsbook line movement and a box score. `Matchup`,
`PropTrends` and `HeadToHead` already existed as fully-built, reusable
components — they were just never mounted anywhere except inside the
collapsed `GamePanel` on the Home scoreboard. Anyone who reached a game via a
direct link (a team's schedule row, a player's game log) landed on a
noticeably thinner page than anyone browsing from Home. Added all three,
lazy-mounted via the existing `LazySection`, ordered so context (form, rest,
betting record, injuries/absences) comes before the charts rather than after.

What changed (stats added): Matchup context, prop trend history, and head-to-
head record now render on the dedicated game page. Also surfaced
`GameRow.season_type` as a badge so a preseason/All-Star game explains its
own missing sportsbook line instead of looking broken (AGENTS.md: those
games are largely unpriced by books).

Backend endpoint(s) newly wired: none new — `/games/{id}/matchup`,
`/games/{id}/trends`, `/teams/{a}/head-to-head/{b}` were already called
elsewhere; this loop was about reuse, not new fetches.

Verification: lint ✅, build ✅
Commit: f85a923 feat: wire matchup context, prop trends and head-to-head into GameDetail

## Loop 2: Playoff race status and shot-defense chart on the team page

Pages/files touched: `frontend/src/components/ui.tsx`, `frontend/src/pages/Teams.tsx`,
`frontend/src/pages/TeamDetail.tsx`

What changed (UX): `RaceBadge` (clinched / eliminated / in position / still
alive) lived only in `Teams.tsx` as a local function, so a team's own page
showed a bare seed number with no read on whether the race is settled.
Extracted it to `ui.tsx` as a shared primitive (`RaceStatus` interface) that
both the full `StandingRow` and the lighter `StandingRowLite` carried on a
team profile satisfy structurally — the lite version has no
`in_playoff_position` field, so the badge infers it from
`games_behind_playoff === 0` when that's all it's given.

What changed (stats added): `/teams/{id}/defense` (shot-location defense —
distinct from the by-position rank table already there) existed only inside
the game-panel matchup view. The team page's "Shot profile" section showed
offense only; it now has a mirrored "Shot defense" section using the same
`ShotChart` component, so a reader can see *where* on the floor a defense
gives up its damage, not just how much by position.

Backend endpoint(s) newly wired: `/teams/{id}/defense` (previously fetched
only from `GamePanel`, now also from `TeamDetail`).

Verification: lint ✅, build ✅
Commit: b616a20 feat: playoff race status and shot-defense chart on the team page

## Loop 3: Injury source and job run counts

Pages/files touched: `frontend/src/lib/injury.ts`, `frontend/src/components/Matchup.tsx`,
`frontend/src/components/Absences.tsx`, `frontend/src/pages/Research.tsx`

What changed (UX/stats added): `InjuryRow.source` and `AbsentPlayer.source`
(`wnba_official` vs `espn`) were fetched everywhere an injury report renders
but never displayed — so a "Day-To-Day" tag, which is the *ceiling* of
ESPN's WNBA vocabulary, looked identical to a real league-filed designation
like Questionable or Doubtful. Added a `sourceLabel()` helper and wired it
into the matchup injury list (inline) and the availability breakdown
(tooltip on the status badge).

Research's job-health grid had `failures_24h`, `runs_24h` and `description`
on `JobHealth` but rendered only name, status, and time since last success.
A job that ran 40 times with 3 failures and one that ran once and failed
once read identically before this. Now the run count and any failures show
as a second detail line, and the job's description is on hover.

Backend endpoint(s) newly wired: none — both fields were already in
responses being fetched (`/health/jobs`, `/games/{id}/matchup`), just
unrendered.

Verification: lint ✅, build ✅
Commit: a823eba feat: surface injury source and job run counts, not just current status

## Loop 4: Sortable table columns

Pages/files touched: `frontend/src/lib/useSort.ts` (new), `frontend/src/components/ui.tsx`,
`frontend/src/styles/global.css`, `frontend/src/pages/Players.tsx`,
`frontend/src/pages/TeamDetail.tsx`

What changed (UX): Players and a team's roster table each had exactly one
fixed sort order (scoring, then minutes) with no way to ask "who plays the
most minutes" or "who has the most assists" without leaving the page. Built
a small `useSort` hook (`lib/useSort.ts`) and a `SortTh` clickable header
cell (`ui.tsx`), explicitly scoped to client-side-loaded tables only — never
wire this to a server-paginated list, since sorting a visible page out of a
larger unfetched set would misrepresent the full ranking. Numeric-looking
API strings (most per-game averages arrive as strings to preserve a
trailing zero) sort numerically, not lexicographically; nulls sort last in
either direction.

A real gotcha hit and documented in both files: hooks can't be called
inside `Async`'s render-prop `children` — it only invokes that function once
data exists, so a hook there fires on some renders and not others and
breaks React's hook-order rule. Both `useSort` calls sit at the top of their
page component instead, fed `query.data?.rows ?? []`.

Backend endpoint(s) newly wired: none — this loop added a UI capability, not
new data.

Verification: lint ✅, build ✅
Commit: ff533e0 feat: sortable table columns on the Players and roster tables

## Loop 5: Games team filter, plus accessibility fixes

Pages/files touched: `frontend/src/pages/Games.tsx`, `frontend/src/pages/Home.tsx`,
`frontend/src/components/PropLines.tsx`

What changed (UX): Games had a season picker and nothing else — no way to
see one team's schedule without scanning the whole slate. Added a
client-side team filter built from the games already on screen (every team
playing this season necessarily appears in its own schedule, so no extra
request is needed). The empty state distinguishes "this team played nothing
this season" from "the filter matched nothing." Also added the same
`season_type` badge from Loop 1 to each row in the Games list, for
consistency.

Two accessibility gaps fixed: Home's Earlier/Later day-nav buttons had only
a `title` attribute (not reliably exposed by screen readers) — added
explicit `aria-label`s. PropLines' clickable market-summary rows had a click
handler and a pointer cursor but no keyboard path: a `<tr>` is not natively
focusable or actionable, so it needed `role="button"`, `tabIndex={0}`, and
an Enter/Space `onKeyDown` handler to be usable without a mouse.

Backend endpoint(s) newly wired: none.

Verification: lint ✅, build ✅
Commit: d791620 feat: team filter on Games, plus keyboard and label accessibility fixes

---

## State for next agent (loops 6-10)

**Pages still thin on stats or UX**, roughly in order of opportunity:

- **PlayerDetail** — no advanced-efficiency stats. `/efficiency` (usage_pct,
  true_shooting, net_rating) is fetched league-wide for the League page's
  scatter plot but a single player's own efficiency numbers never surface on
  their own profile. Either add a per-player efficiency lookup (filter the
  existing `/efficiency?season=` response client-side, or check if the
  backend supports a `player_id` filter — grep `wnba_engine/api/routes/shooting.py`)
  or add three `Stat`s to the header. Also: no indicator if the player is
  *currently* on an injury report — would need to check the team's injuries
  from `/games/{id}/matchup` context or add a small dedicated lookup; not
  attempted here because there's no direct "this player's current status"
  endpoint, only per-team injury lists.
- **Home** — reasonably dense already (SlateBar, SlateTrends, full GamePanel
  per game). Diminishing returns; if revisited, check whether the day-nav
  Earlier/Later interaction has a keyboard shortcut (arrow keys) — currently
  mouse/tab-only.
- **Research** — `/divergences` (the raw per-observation list, as opposed to
  `/divergences/summary` which is wired) is completely unused. Could support
  a "recent observations" expandable table under the venue summary cards, but
  weigh it against the page's own framing ("a forward experiment in
  progress, not a result") — a raw log might invite over-reading single
  observations the prose explicitly warns against.
- **Games / TeamDetail schedule table** — not sortable (loop 4 only touched
  Players and the roster table). Chronological order is probably correct for
  Games, but the TeamDetail schedule table (date, opponent, result, spread,
  ATS, total, O/U) could reasonably sort by any numeric column the same way
  the roster table now does — same `useSort`/`SortTh` primitives apply
  directly.
- **NotFound / Model** — deliberately minimal (NotFound) or already dense and
  narrative-driven (Model, the paid-tier page) — probably leave alone.

**Backend endpoints checked and confirmed already wired somewhere**
(don't re-discover these as "unused" — they're just not on every page that
could plausibly use them): `/teams/{id}/defense`, `/players/{id}/props`,
`/lines/market-props`, `/teams/{a}/head-to-head/{b}`, `/games/{id}/trends`,
`/games/{id}/matchup`, `/defense/by-position`.

**Backend endpoints genuinely unused anywhere in the frontend**:
`/divergences` (raw list — see Research note above), `/health` (bare
liveness check, distinct from `/health/jobs` which the Research page already
uses — probably not useful to surface in the UI at all).

**Correction from the second agent**: `/summary` (dataset overview) is
already wired, into League.tsx's "Dataset" section — it just wasn't listed
above. Confirmed by grepping every fetched path in `frontend/src` rather
than trusting this file's own list, per the task's own instruction not to
take the handoff notes on faith. It is the one entry in "confirmed already
wired" that this file omitted; everything else in that list checked out.

---

## Loop 6: Usage, true shooting and net rating on a player's own page

Pages/files touched: `frontend/src/pages/PlayerDetail.tsx`

What changed (stats added): `/efficiency` (usage_pct, true_shooting,
net_rating) was fetched league-wide for League's usage-vs-TS scatter but a
player's own profile never showed their own number, exactly as the loop-5
handoff flagged. The backend has no `player_id` filter on that route
(checked `wnba_engine/api/routes/shooting.py` directly rather than trusting
the log's guess) so the same response is fetched again here, scoped to the
selected season, and the one matching row is picked out client-side.
`min_games=1` deliberately, not the leaderboard's 10 — this is a single
player's own profile, so their number should show even in a short season
rather than silently disappearing under someone else's cutoff.

What changed (UX): Three new `Stat`s in the header, alongside PPG/RPG/APG/
FG%/3P%, shown only when the player has a row for the selected season (a
DNP season or one with too few appearances shows the existing five stats
without a gap).

Backend endpoint(s) newly wired: none new — `/efficiency` was already
fetched from League; this is a second, differently-scoped call to the same
route from a different page.

Verification: lint ✅, build ✅
Commit: 5b5d269 feat: surface usage, true shooting and net rating on a player's own page

## Loop 7: Sortable schedule table on a team's page

Pages/files touched: `frontend/src/pages/TeamDetail.tsx`

What changed (UX): The roster table got click-to-sort in loop 4; the
schedule table (date, opponent, result, spread, ATS, total, O/U) was left
in date order only, exactly as the loop-5 handoff flagged. Added `SortTh`
on Date, Spread and Total using the same `useSort` hook already imported
for the roster — no new primitive needed. Deliberately no initial sort key,
so the default view stays chronological and only reorders once someone
actually clicks a header, unlike the roster table which opens sorted by
minutes.

Backend endpoint(s) newly wired: none — UI capability only, same caveat as
loop 4: client-side sort is only safe here because the schedule is fetched
whole, not paginated.

Verification: lint ✅, build ✅
Commit: 1aa1f44 feat: sortable schedule table on a team's page

## Loop 8: Keyboard day navigation on Home

Pages/files touched: `frontend/src/pages/Home.tsx`

What changed (UX): The loop-5 handoff noted Home's Earlier/Later day-nav
was mouse/tab-only with no keyboard shortcut. Added a `keydown` listener
for ArrowLeft/ArrowRight that steps the same `offset` state the buttons
already drive, disabled at the same boundaries (`canGoEarlier`/
`canGoLater`, now shared between the buttons and the listener instead of
each recomputing `index >= days.length - 1` separately). Ignored while a
form control (`input`/`textarea`/`select`) has focus, so it never hijacks a
season picker or search box's own use of the same keys on another page —
this page has no such control today, but the guard costs nothing and keeps
the pattern safe to copy elsewhere. The buttons' `aria-label`s now mention
the shortcut so it's discoverable, not just functional.

Backend endpoint(s) newly wired: none.

Verification: lint ✅, build ✅
Commit: 1f09ce8 feat: left/right arrow keys step through Home's day nav

## Loop 9: Expandable raw divergence log on Research

Pages/files touched: `frontend/src/lib/api.ts` (new `DivergenceObservation`
interface), `frontend/src/pages/Research.tsx`

What changed (stats added): `/divergences` — the itemized, per-observation
list, distinct from `/divergences/summary` which the page already used —
was confirmed still unused anywhere in the frontend (re-grepped every
fetched path rather than trusting the "genuinely unused" list at face
value; it held up). Added it behind a "Show log" toggle so it's fetched
only once opened, not on every page load: the aggregates above are what the
page's own prose says is the real content, and the surrounding text is
explicit that a survival rate needs its denominator to mean anything, which
argues against making the raw per-row list prominent. The table itself
(captured time, matchup linked to `/games/:id`, venue, side, edge, whether
the price survived, CLV) stays collapsed by default with a one-line note
in its place explaining what it is and isn't.

Backend endpoint(s) newly wired: `/divergences` (previously fetched
nowhere in the frontend).

Verification: lint ✅, build ✅
Commit: 215a1e6 feat: expandable raw divergence log on Research

## Loop 10: Retry on every failed request

Pages/files touched: `frontend/src/lib/api.ts`, `frontend/src/components/ui.tsx`,
`frontend/src/components/GamePanel.tsx`

What changed (UX): Not a single page — the shared `Async`/`useQuery` layer
every page and component renders through. A failed request (network blip,
backend hiccup) previously rendered "Could not load this: ..." with no way
to recover short of a full page reload. `useQuery` now tracks an internal
`attempt` counter and returns `refetch()`, which bumps it to re-run the
same fetch without changing `path`. `Async`'s error branch renders a Retry
button wired to it. Fixing this surfaced a real duplication: `GamePanel.tsx`
had its own hand-written copy of the query-shape type for `SportsbookProps`
(`{ data, error, loading }`, no `refetch`), which the compiler caught the
moment `refetch` became required — replaced with the exported `Query<T>`
type from `lib/api.ts` instead of hand-rolling it again.

What changed (stats added): none — pure reliability/UX fix, applies
uniformly to every `Async` usage across all 11 pages without touching any
of them individually.

Backend endpoint(s) newly wired: none.

Verification: lint ✅, build ✅
Commit: 031b443 feat: retry button on every failed request, not just a page reload

---

## Summary — all 10 loops

1. Wire matchup context, prop trends and head-to-head into GameDetail —
   reused three already-built components on the standalone game page.
2. Playoff race status and shot-defense chart on the team page — extracted
   `RaceBadge` as a shared primitive, mirrored offense's shot chart on
   defense.
3. Injury source and job run counts — surfaced fields that were already in
   API responses but never rendered.
4. Sortable table columns on Players and the roster table — new
   `useSort`/`SortTh` primitives, client-side only by design.
5. Games team filter, plus keyboard/label accessibility fixes on Home and
   PropLines.
6. Usage, true shooting and net rating on a player's own page — filtered
   the league-wide `/efficiency` response down to one player.
7. Sortable schedule table on the team page — same `useSort`/`SortTh`
   primitives applied to the one client-side-loaded table loop 4 missed.
8. Keyboard day navigation on Home — arrow keys mirror the existing
   Earlier/Later buttons.
9. Expandable raw divergence log on Research — the last unused analytics
   endpoint, wired in deliberately understated so it doesn't compete with
   the page's own caution against over-reading raw observations.
10. Retry on every failed request — a shared-primitive fix (`useQuery` +
    `Async`) that improves error recovery on all 11 pages at once, not a
    single-page change.

**Current state**: `npm run lint` (tsc -b --noEmit) and `npm run build`
(tsc + vite build) both pass with zero errors as of the loop 10 commit.
11 commits ahead of `main` (5 from loops 1-5, the loop 1-5 log commit, 5
from loops 6-10; this log commit will make it 12).

**What's still NOT covered, honestly:**

- **NotFound.tsx and Model.tsx** were never touched across all 10 loops.
  Both were flagged in the loop-5 handoff as deliberately out of scope —
  NotFound is a minimal 404 by design, Model is the dense, narrative-driven
  paid-tier page — and that judgment held up on a second look; neither
  showed an obvious gap worth forcing a change into.
- **GameDetail.tsx** was the loop 1 target and hasn't been revisited since
  — it's dense (matchup, trends, head-to-head, box score, flow, lines) but
  wasn't re-audited for anything new in loops 6-10.
- **`/health`** (the bare liveness check, distinct from `/health/jobs`)
  remains the one backend endpoint confirmed genuinely unused anywhere in
  the frontend, and deliberately so — it's a liveness probe, not user-
  facing data, and Research's job-health grid already covers the
  freshness/reliability story a reader actually wants.
- **Players.tsx** still can't sort by rebounds, assists, steals or blocks —
  `PlayerRow` (the `/players` list response) only carries `points` and
  `minutes` per row. Adding those columns would need a backend change
  (out of scope here: frontend-only, per the task's own constraints), or a
  swap to a different, richer endpoint if one exists that wasn't found in
  this pass.
- No frontend test suite exists in this repo (`frontend/package.json` has
  no test runner configured) and none was added — verification for all 10
  loops was lint + build only, matching the gate this task was scoped to.
- This worktree has not been merged into `main` and nothing was pushed;
  it's left as-is for review.
