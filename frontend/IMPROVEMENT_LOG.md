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
