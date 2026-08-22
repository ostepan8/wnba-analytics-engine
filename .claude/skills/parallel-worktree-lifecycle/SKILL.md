---
name: parallel-worktree-lifecycle
description: Mandatory lifecycle for any code change in this repo -- isolate the work in a git worktree, keep AGENTS.md and the relevant .claude/skills/ current as part of the same change, and merge back with explicit conflict handling. Required because many agents edit this repo concurrently. Load before the first Edit/Write of any implement/fix/refactor/add-feature/data-pipeline/frontend task, and again before merging a worktree branch back to main.
---

# Parallel worktree lifecycle

This repo is worked on by many agents at once, often in parallel worktrees.
Skipping any of the three phases below doesn't just risk your own task --
it corrupts shared state (`main`, `AGENTS.md`, migration numbering, skill
files) that every other agent currently running is reading or about to
merge into. Treat all three phases as one atomic unit of work, not
optional cleanup.

## Phase 1 -- Always start in a fresh worktree

Never run `Edit`/`Write` against tracked files while `cwd` resolves to the
repo root on `main`. Before the first edit:

**If the `EnterWorktree` tool is available (Claude Code session):**
```
EnterWorktree({ name: "<kebab-task>" })
```
This creates the worktree under `.claude/worktrees/` on a fresh branch off
`origin/main` and switches the session into it. Use `ExitWorktree` when
done (`keep` if the user wants to return to it, `remove` for a clean exit
after merging).

**Otherwise (manual, or orchestrating from a script):**
```bash
git fetch origin 2>/dev/null || true
git worktree add -b wt/<kebab-task> .claude/worktrees/<kebab-task> main
cp .env .claude/worktrees/<kebab-task>/    # gitignored, needed for integration tests
cd .claude/worktrees/<kebab-task>
```

**If spawning parallel subagents from within a session** (via the `Agent`
tool) to edit files concurrently, pass `isolation: "worktree"` on each
call that writes -- this gives each subagent its own worktree automatically
and avoids two agents racing on the same files. Don't skip this for
concurrent file-writing agents just because it's "only" a small edit.

**A background fork/subagent's working directory is pinned to wherever
your session's `cwd` was at the moment you launched it -- not wherever the
prompt tells it to work.** If you spawn a long-running background fork
while your own session is inside a worktree (even if its prompt says
"work in the main repo, not a worktree"), its file writes still land in
that worktree, because cwd is a launch-time property the prompt can't
override. This already cost a near-loss: a fork was launched from inside
`.claude/worktrees/add-mcp-server`, ran for 7+ minutes producing a real
research doc, and that worktree was removed (`git worktree remove
--force`, work already merged) before the fork finished -- its final
`Write` silently recreated the directory as an untracked orphan instead of
failing, and the doc almost got lost with the next cleanup pass. Two
mitigations: exit the worktree (`ExitWorktree`) or launch from the main
checkout *before* spawning a background agent that will outlive your own
worktree's lifecycle; and before removing any worktree, check
`ListAgents` for still-running children that might be writing into it.

## Phase 2 -- Update docs and skills as part of the change, not after

Before you consider the implementation done -- not as a follow-up commit --
check whether your change invalidates anything another agent would read to
orient itself:

- **`AGENTS.md`** -- update it if you changed: the architecture/layering
  rules, a landmine's status (e.g. you made an "unrecoverable" feed
  recoverable, or found a new provider quirk), the deployment/ops
  procedure, or a validated invariant (idempotency keys, point-in-time
  safety, cost/credit accounting).
- **The relevant `.claude/skills/*/SKILL.md`** -- if a skill in this repo
  documents an area you touched (a provider package, the pipeline layer,
  the frontend, deployment), update it in the same commit. A stale skill
  is worse than no skill: another agent will trust it and act on wrong
  information.
- **`wnba_engine/features/README.md`** and other in-tree READMEs -- same
  rule, if you touched that package.

If nothing you changed is documented anywhere and doesn't need to be
(a pure bugfix with no new convention), it's fine to skip this -- don't
pad commits with busywork. The bar is: would another agent, reading only
the docs, be misled by *not* knowing what you just did?

**Never write a "currently X" / "known issue" / "as of &lt;date&gt;" claim
into a doc or skill without checking it against live state first.** This
bit a real skill-authoring pass: a mapping agent read `AGENTS.md` and
`deploy/schedule.toml`'s comments, wrote "ESPN injuries 403ing since
2026-08-16" and "sportsbook lines feed stalled since 2026-08-10" into
`runtime-services/SKILL.md` as fact, and both had already silently
resolved days earlier -- the claims were copied from another doc, not
re-verified. Static analysis of code and comments cannot tell you whether
an operational claim is still true; only checking live signals can (here:
`https://wnba.onephos.com/api/health/jobs`, `/api/summary`, and
`ssh fedora` + a read-only query against `job_runs`/the relevant table's
`max(captured_at)` -- see the deploy pipeline reference for exact commands).
If you can't verify live, either omit the claim or date-stamp it explicitly
as unverified/point-in-time so the next reader knows to re-check rather
than propagate it further.

## Phase 3 -- Merge back, handling conflicts explicitly

Before merging into `main`, assume other agents merged ahead of you:

```bash
git fetch origin main
git merge origin/main          # or rebase, if you prefer a linear history for this task
```

Resolve conflicts by reading both sides, not by blindly taking
`--ours`/`--theirs`:

- **`db/migrations/` numbering collisions** are the most likely conflict
  under concurrent work -- migrations are numbered sequentially and
  append-only. If two agents both added `00NN_*.sql`, **renumber yours to
  the next free number** after rebasing; never let two migrations share a
  number, and never renumber a migration another branch already merged
  and that may have run against a live database.
- **`AGENTS.md` / `SKILL.md` conflicts** -- these usually mean two agents
  documented two different things in the same section. Keep both additions
  (reword to fit together) rather than dropping one agent's knowledge.
- **Any append-only-table idempotency constraint** -- if your merge touches
  the same table another branch also touched, re-check the `UNIQUE`
  constraint still matches the natural key after both changes land.

After the merge resolves cleanly:

```bash
uv run wnba-engine migrate      # if migrations changed
uv run pytest -q
uv run ruff check .
uv run wnba-engine validate     # if repository/pipeline code changed
```

Only merge into `main` (`git merge --no-ff wt/<kebab-task>`) after these
pass against the *merged* state, not just your branch in isolation --
tests green on your branch prove nothing about what another agent's
concurrent merge broke.

Then clean up:
```bash
git worktree remove .claude/worktrees/<kebab-task> --force
git branch -d wt/<kebab-task>
```
(or `ExitWorktree({ action: "remove" })` if you entered via the native tool).

## Why this is one skill, not three

Opening a worktree without later updating docs leaves other agents working
off a stale map. Updating docs without disciplined merge-back means the
update itself gets lost to a conflict. Merging carefully without having
started in a worktree is moot -- you already edited `main` directly. Treat
Phases 1-3 as a single required lifecycle for every task in this repo.
