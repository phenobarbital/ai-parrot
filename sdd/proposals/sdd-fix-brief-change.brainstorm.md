---
type: feature
base_branch: dev
projects: [sdd-tooling, docs]
tags: [sdd-fix, fix-lane, worktree, ledger, pull-request]
---

# Brainstorm: Fast lane runs in its own worktree (never the main checkout)

**Date**: 2026-10-24
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

`/sdd-fix`'s **Fast lane** is specified to work *in the main checkout*:

> `- **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev`, …`
> — `.claude/commands/sdd-fix.md:36` (and its two twins)

That single instruction is the whole problem. Running it:

1. **moves the main checkout off `dev`** onto `fix/<id>-<slug>` and leaves it
   there — every later command in that session (`/sdd-spec`, `/sdd-task`,
   `reserve_ids.py`, a plain `git log`) now resolves against a fix branch
   instead of `dev`;
2. **collides with parallel sessions.** This repo routinely runs several Claude
   sessions against the same primary checkout. A `git switch -c` in the shared
   tree re-points *their* `HEAD` too: their commits land on the fix branch, and
   an unrelated session's `reset --hard origin/dev` can eat the fix. This
   hazard is already documented repo-side (`.claude/rules/worktree-management.md`,
   "all feature edits happen inside `<path>` — never in the primary checkout");
3. **requires a clean checkout** as a precondition (`sdd-fix.md:34`, "Before
   changing branches, require a clean checkout"), so the lane refuses to run
   whenever the main tree has any unrelated edit — a frequent, pointless block;
4. **leaves the branch behind** with no cleanup step at all: after the PR is
   opened the main checkout is still on the fix branch and nothing switches back.

Who is affected: whoever runs `/sdd-fix` (today: the repo owner, plus the
`sdd-fix` agent lane), and every concurrent session sharing the checkout.

Why now: the fix lane is the highest-frequency SDD entry point — there are 20+
`fixgroup-*.spec.md` specs in `sdd/specs/` from past drains — so the blast
radius of "it mutates the shared tree" is paid repeatedly.

**Deliberately out of scope** (decided in discovery):

- **`/sdd-brief` keeps its current shape.** It already provisions a worktree
  through `python -m scripts.sdd.ensure_worktree --json --slug <slug>
  --brief-key <KEY> --base-branch <base>` (`.claude/commands/sdd-brief.md`
  Step 9) and already forbids touching the main checkout's `sdd/` (its
  Guardrails). Its worktree must *survive* the command, because implementation
  happens inside it (`cd <wt> && claude --agent sdd-worker`), so a PR can only
  exist after the code does — that is `/sdd-done <KEY>`'s job, and `/sdd-done`
  already opens the PR against `base_branch` and reaps the worktree
  (`.claude/commands/sdd-done.md:116-126`, `:868-870`). The only brief-side
  change this brainstorm carries is making that hand-off impossible to miss.
- **`/sdd-fix`'s SDD lane keeps its current shape**: the FEAT id reservation and
  the spec/task commits stay in the main checkout on `dev`, because the worktree
  is cut from `origin/dev` and must therefore find the spec and index already
  there. The main checkout *stays on* `dev` in that lane — it only gains commits.

---

## Constraints & Requirements

- The main checkout must never change branch, and must never be required to be
  clean, for a Fast-lane fix.
- Always a PR to `base_branch` (`dev` for the Fast lane) — no direct-push path.
  `tests/sdd/test_sdd_fix_docs.py:25` asserts the literal string
  `gh pr create --base dev` survives in `docs/sdd/WORKFLOW.md`.
- One worktree + one PR **per group** (`--top N` → N worktrees, created and
  reaped in sequence), so each group stays independently reviewable/revertable.
- The worktree is removed after a successful push + PR; the branch lives on
  `origin`, and a tree is re-provisioned on demand if review feedback arrives.
- On any failure (tests, commit, push, `gh pr create`): **keep the worktree**
  (report its path) and **release the ledger claims** so another run can take
  the issues.
- Cleanup must never discard work: the reaper must refuse on dirty/unpushed,
  i.e. `--force` is forbidden on this path.
- Ledger reads/writes still resolve to the main checkout
  (`.claude/commands/sdd-fix.md:9-11`); this is legal from inside a worktree
  because the primary checkout's `.parrot/ledger/` is mounted writable
  (`.claude/rules/worktree-management.md:55`).
- Tests run *inside* a worktree need an explicit `PYTHONPATH=packages/<dist>/src`
  — a bare `pytest` in a worktree imports the main checkout's code and yields a
  false result (`.claude/rules/worktree-management.md` §4).
- Never hand-roll `git worktree add`; provisioning goes only through
  `scripts.sdd.ensure_worktree` (same rule, §2).
- The three `/sdd-fix` twins must stay in lockstep: `.claude/commands/sdd-fix.md`,
  `.agents/skills/sdd-fix/SKILL.md`, `.agent/workflows/sdd-fix.md`.

---

## Options Explored

### Option A: Reuse the brief worktree plan (`ensure_worktree --brief-key`) for the Fast lane

Change the Fast lane's five lines of policy to provision a dedicated worktree
through the CLI that already exists, do all the work with `git -C <wt>`, and
reap it with the reaper that already exists.

`scripts/sdd/brief_meta.py:150-173` already plans exactly the tree the Fast lane
wants: with a non-`main` base it yields `prefix = "fix"` and
`name = f"{prefix}-{key}-{slug}"` → `.claude/worktrees/fix-<id>-<slug>` based on
`origin/dev`. `ensure_worktree`'s `--brief-key` is documented as taking a "Jira
key, **ledger short id**, or slug" (`scripts/sdd/ensure_worktree.py:305-310`) —
the ledger short id is precisely the Fast lane's identity. So the new lane is:

1. `python -m scripts.sdd.ensure_worktree --json --slug <suggested_slug> --brief-key <issue-short-id> --base-branch dev` → `<wt>`
2. edit inside `<wt>`; run the affected package's tests with `PYTHONPATH=packages/<dist>/src`
3. `git -C <wt> add <files> && git -C <wt> commit && git -C <wt> push -u origin fix-<id>-<slug>`
4. `gh pr create --base dev --head fix-<id>-<slug> …`
5. close the ledger issues (`--resolved-by commit:<sha>`), then
   `python scripts/remove_worktree.py remove fix-<id>-<slug>` — **no `--force`**,
   **no `--delete-branch`**
6. on any failure: keep `<wt>`, `ledger unclaim` everything claimed, report the path

No new Python, no new CLI surface: `ensure_worktree` already clears the
auto-upstream so step 3's `-u` is the explicit first push, already syncs the
gitignored native `.so` artifacts into the tree (FEAT-722) so step 2's tests can
actually import the Cython modules, and `remove_worktree.py` already refuses to
remove a tree with uncommitted changes (`scripts/remove_worktree.py:298-307`) or
with commits origin does not have (`:309-313`) — which is exactly the
"never reap before the push landed" guard, for free.

✅ **Pros:**
- The main checkout never changes branch and never needs to be clean.
- Zero new code: it deletes a bespoke path in favour of two scripts that are
  already the repo's blessed, tested way to create and destroy worktrees.
- Branch name doubles as the worktree directory name, so the lane is
  self-describing in `git worktree list` and in `/sdd-status`.
- The "don't reap unpushed work" invariant is enforced by `remove_worktree.py`,
  not by prose the agent has to remember.
- The failure path ("keep the tree, release the claims") is a *natural* outcome:
  the reaper simply refuses, and the dirty tree is the evidence.

❌ **Cons:**
- Branch naming changes from `fix/<id>-<slug>` to `fix-<id>-<slug>` (a git
  *directory* name cannot carry the `/`), so the convention in
  `docs/sdd/WORKFLOW.md:134` and any muscle memory/PR filters change with it.
- `--brief-key` is named for briefs; using it for the fix lane is a slight
  semantic stretch until/unless a `--fix-key` alias is added.
- Still policy-in-prose: three twin documents must agree, and nothing *fails*
  if a future agent re-reads an old copy.
- Each group pays worktree creation cost (checkout + native artifact sync)
  where today it paid none.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `scripts.sdd.ensure_worktree` (repo-local) | idempotent worktree provisioning | already the only sanctioned path; `--brief-key` + `--base-branch dev` → `fix-<KEY>-<slug>` |
| `scripts/remove_worktree.py` (repo-local) | safe reaping | `remove <target>`; refuses dirty/unpushed without `--force` |
| `gh` (GitHub CLI) | `gh pr create --base dev` | already used by the Fast lane today |
| `wikitoolkit ledger` | plan-fix / claim / close / unclaim | unchanged; resolves to the main checkout |

🔗 **Existing Code to Reuse:**
- `scripts/sdd/brief_meta.py:150` — `brief_worktree_plan()`, already yields the `fix-<KEY>-<slug>` plan on a non-`main` base
- `scripts/sdd/ensure_worktree.py:305` — `--brief-key`, documented to accept a ledger short id
- `scripts/remove_worktree.py:406` — the `remove` subcommand with its dirty/unpushed refusals
- `.claude/commands/sdd-brief.md` Steps 9–11 — the already-proven "provision → write → commit → push from `<wt>`" shape to copy verbatim

---

### Option B: A deterministic `scripts/sdd/fix_lane.py` driver

Move the whole Fast lane into Python: one script that takes a group from the
`FixPlan` and performs provision → edit hand-back → test → commit → push → PR →
close → reap, with the failure semantics (keep tree, unclaim) as code paths and
unit tests. The command docs shrink to "run `python -m scripts.sdd.fix_lane
--group <id>`".

This follows the repo's own precedent for turning fragile prose into a tested
script: `ensure_worktree.py` (FEAT-552) replaced hand-rolled `git worktree add`
blocks in six commands, and `close_task.sh` / `finalize_task.py` replaced
hand-rolled task closure.

✅ **Pros:**
- The invariants become executable and unit-testable (no twin drift, no
  "the agent forgot the PYTHONPATH prefix", no reap-before-push).
- A single place to add the per-group loop, the `--dry-run`, and the
  release-on-every-exit-path guarantee that step 7 currently asks prose to do.
- Would also let `/sdd-fix` report machine-readable per-group results.

❌ **Cons:**
- The editing itself cannot be scripted — the agent must be handed the tree and
  called back, so the driver ends up as two or three subcommands with state
  between them, which is a genuinely larger design than it first looks.
- New Python surface (plus tests) to maintain for what is otherwise six shell
  commands; duplicates logic already inside `ensure_worktree` and
  `remove_worktree.py`.
- Medium-to-high effort for the same user-visible outcome as Option A.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `argparse` + `subprocess` (stdlib) | driver CLI | same shape as `ensure_worktree.py` |
| `pydantic` v2 | typed FixPlan/group models | repo standard for data structures |
| `pytest` | unit tests for the lane | `tests/sdd/` |

🔗 **Existing Code to Reuse:**
- `scripts/sdd/ensure_worktree.py:74` — `ensure(plan, *, repo_root, …) -> tuple[Path, bool]`, callable in-process
- `scripts/sdd/brief_meta.py:150` — the worktree plan builder
- `scripts/sdd/finalize_task.py` — the precedent for a deterministic, evidence-emitting SDD driver

---

### Option C: Delete the Fast lane and route single-file fixes through `/sdd-brief`

Unconventional/consolidating: stop having two lanes. `/sdd-fix` keeps the
planner, the claim and the close, but for `lane == "fast"` it simply invokes
`/sdd-brief issue:<id>` and lets the brief machinery own everything downstream —
worktree, research floor, `HOTFIX-<KEY>-<N>` task files — with `/sdd-done <KEY>`
opening the PR and reaping the tree.

✅ **Pros:**
- One lane shape to document, one worktree convention, one PR/cleanup owner.
- Inherits the brief's research floor (root cause + a verified `path:line`
  anchor), which a Fast-lane fix currently has no obligation to produce.
- The main-checkout problem disappears by construction.

❌ **Cons:**
- Ceremony explosion: a two-line `tech_debt` fix acquires a brief document, a
  task file and a per-brief index, plus `check_task_graph` validation.
- Contradicts the decision that `/sdd-fix` should finish the job **inline**: the
  brief lane deliberately hands off, so the PR arrives one command later and the
  worktree outlives the `/sdd-fix` run — the exact complaint that started this.
- Loses the Fast lane's reason to exist (the planner routes `minor`/`low`
  single-file `tech_debt` there *precisely* to skip SDD ceremony).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `scripts/sdd/brief_meta.py` | brief identity, index, task ids | already handles ledger-sourced briefs (`ledger ⇒ dev`) |
| `scripts/sdd/check_task_graph.py` | per-brief index validation | required by the brief lane |

🔗 **Existing Code to Reuse:**
- `.claude/commands/sdd-brief.md` Steps 2–12 — the entire lane, unchanged
- `.claude/commands/sdd-done.md:116` — the brief branch of `/sdd-done`

---

### Option D: Keep the main checkout, add a precondition and a restore

Minimal: leave `git switch -c` in the main checkout, but require the checkout to
be on `base_branch` and clean before switching, and mandate `git switch -` (back
to the original branch) on every exit path, success or failure.

✅ **Pros:**
- Smallest possible diff; no worktree cost per group; branch name `fix/<id>-<slug>` unchanged.
- Fixes the narrow "left the main checkout on a fix branch" symptom.

❌ **Cons:**
- Does **not** fix the real hazard: during the fix, the shared `HEAD` still
  points at the fix branch, so a parallel session's commits still land there and
  a parallel `reset --hard` still eats the fix.
- Keeps the "main checkout must be clean" blocker.
- A restore-on-every-exit-path promise in prose is exactly the kind of guarantee
  that is silently skipped when a run is interrupted.

📦 **Libraries / Tools:** none (pure doc change).

🔗 **Existing Code to Reuse:**
- `.claude/commands/sdd-fix.md:36` — the existing lane text, amended in place

---

## Recommendation

**Option A** is recommended.

The defect is *in the instruction itself* — the Fast lane is told to branch in
the main checkout — so correcting the instruction genuinely fixes it; this is not
a case of an agent disobeying good prose. And the correction costs no new code,
because the two dangerous steps (creating and destroying a worktree) already
have blessed, tested implementations that other lanes use:
`ensure_worktree --brief-key … --base-branch dev` already produces precisely the
`fix-<KEY>-<slug>` tree this lane needs (`brief_meta.py:166-167`), and
`remove_worktree.py`'s dirty/unpushed refusals already encode "never reap work
that is not on origin" as behaviour rather than as a reminder.

What is being traded away:

- **Branch naming.** `fix/<id>-<slug>` becomes `fix-<id>-<slug>`. Acceptable:
  the name now doubles as the worktree directory, which makes the lane visible
  in `git worktree list` and `/sdd-status`, and `docs/sdd/WORKFLOW.md:134` is
  updated in the same change.
- **Per-group setup cost.** Each group pays a worktree checkout plus a native
  artifact sync. Acceptable against the alternative of corrupting a shared tree,
  and it buys correct in-worktree tests (with the `PYTHONPATH` prefix) instead of
  tests that silently imported the main checkout.
- **Option B's enforcement.** Rejected *for now*, not on merit: the editing step
  cannot be scripted, so the driver would be a multi-call stateful CLI — a much
  larger design for the same visible outcome. If twin drift or a skipped reap
  shows up in practice, B is the natural follow-up and Option A leaves the door
  open (its steps are already script calls). Logged as an Open Question.

---

## Feature Description

### User-Facing Behavior

Running `/sdd-fix` (any form) no longer changes the main checkout's branch and
no longer requires it to be clean. For each group the planner routes to the Fast
lane, the user sees:

```
Group fixgroup-<id> → Fast lane
  Worktree: .claude/worktrees/fix-<short-id>-<slug>   (created)
  Tests:    PYTHONPATH=packages/ai-parrot/src pytest … ✓
  Pushed:   fix-<short-id>-<slug>
  PR:       https://github.com/phenobarbital/ai-parrot/pull/<n>  (base: dev)
  Closed:   issue:<id> --resolved-by commit:<sha>
  Worktree: removed
```

On failure the last two lines become:

```
  FAILED at <step>: <reason>
  Worktree KEPT: .claude/worktrees/fix-<short-id>-<slug>
  Released: issue:<id> (unclaimed — available for another run)
```

`--top N` repeats that block N times: N worktrees, N PRs, created and reaped one
after another. Nothing in `/sdd-brief` changes for the user; its hand-off line
is just made explicit that `/sdd-done <KEY>` is what opens the PR and removes the
worktree.

### Internal Behavior

Steps 1–4 of `/sdd-fix` (plan / select / claim / prime) are untouched. Step 5's
Fast-lane branch becomes, per group:

1. **Provision** — `ensure_worktree --json --slug <suggested_slug> --brief-key
   <issue-short-id> --base-branch dev`; capture the path. Idempotent: a re-run on
   the same group reuses the tree and re-syncs native artifacts.
2. **Implement** — all edits via `git -C <wt>` / paths under `<wt>`. The main
   checkout is never written to, and its cleanliness is never inspected.
3. **Validate** — the affected package's tests, run from `<wt>` with
   `PYTHONPATH=packages/<dist>/src` (one entry per changed package), plus
   `ruff check --fix` on the changed files.
4. **Commit & push** — stage only the fix's files, commit, then an explicit
   `git -C <wt> push -u origin fix-<id>-<slug>` (the tree has no upstream by
   design).
5. **PR** — `gh pr create --base dev --head fix-<id>-<slug>`, always; no
   direct-push path.
6. **Close** — unchanged two-key rule: the implementing agent asserts the issue
   id *and* at least one of the issue's `files` appears in
   `git -C <wt> diff --name-only <base>...HEAD`. `<base>` is captured before
   implementation; the diff is read from `<wt>`.
7. **Reap** — `python scripts/remove_worktree.py remove fix-<id>-<slug>`,
   without `--force` and without `--delete-branch` (the PR needs the remote
   branch). A refusal here is a *signal*, not a nuisance: it means something is
   uncommitted or unpushed, so the tree is kept and reported.

Step 7 of the command (Release) gains the Fast-lane rule: on any failure in 3–6,
keep the worktree and `ledger unclaim` every issue claimed for that group.

The SDD lane and the ledger mechanics are unchanged; so is `/sdd-brief`.

### Edge Cases & Error Handling

| Situation | Behaviour |
|---|---|
| Worktree already exists for this group (re-run) | `ensure_worktree` is idempotent — reuse it, re-sync native artifacts, continue |
| Tests fail | Keep `<wt>`, unclaim the group's issues, report the failing command; no commit, no PR |
| `push` rejected (branch moved on origin) | Keep `<wt>`, unclaim; report — never `--force`-push and never reset the branch |
| `gh pr create` fails / `gh` unauthenticated | Branch is already pushed: keep `<wt>`, unclaim, and print the exact `gh pr create --base dev --head …` command for the human |
| Reaper refuses (dirty or unpushed) | Keep `<wt>`, report exactly what it found; never pass `--force` to "win" |
| `--top N`, group 2 of 3 fails | Groups 1 and 3 complete normally; only group 2's issues are released and only its worktree is kept |
| Ledger is read-only (sandbox) | Pre-existing rule stands: report `shared ledger is read-only`, claim nothing, exit non-zero — before any worktree is created |
| A plain `pytest` is run inside `<wt>` | False result (imports the main checkout). The lane must always carry the `PYTHONPATH=packages/<dist>/src` prefix |
| `uv sync` / `maturin develop` inside `<wt>` | Forbidden — it re-points the shared venv's `.pth` and breaks `import parrot` for every session |
| Issue's group spans two packages | Both `PYTHONPATH` entries; still one worktree, one PR |

---

## Capabilities

### New Capabilities
- `fix-lane-worktree-isolation`: the `/sdd-fix` Fast lane provisions, works in,
  and reaps its own `fix-<id>-<slug>` worktree, leaving the main checkout untouched.
- `fix-lane-inline-pr-and-cleanup`: a Fast-lane group completes end-to-end inside
  one `/sdd-fix` run — PR to `dev` opened and worktree removed — with a
  keep-tree-and-release failure path.

### Modified Capabilities
- `sdd-fix-ledger-lane` (`sdd/specs/sdd-fix-ledger-lane.spec.md`) — Step 5's Fast
  lane and Step 7's release rule change; Steps 1–4 and 6 keep their contracts.
- `sdd-brief-hotfix-flow` (`sdd/specs/sdd-brief-hotfix-flow.spec.md`) —
  documentation only: the Step 12 hand-off states explicitly that
  `/sdd-done <KEY>` opens the PR and removes the worktree.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.claude/commands/sdd-fix.md` | modifies | Step 5 Fast lane rewritten; Step 7 gains the keep-tree/release rule |
| `.agents/skills/sdd-fix/SKILL.md` | modifies | twin — must match (`tests/sdd/test_codex_sdd_sync.py:41` reads this file) |
| `.agent/workflows/sdd-fix.md` | modifies | twin — must match |
| `docs/sdd/WORKFLOW.md` | modifies | §"Ledger-Driven Fix Lane" line 134: branch naming + worktree; must keep the literal `gh pr create --base dev` |
| `docs/sdd/PLATFORM.md` | modifies | command table row 263: "Fast lane (branch + PR)" → worktree + PR + reap |
| `tests/sdd/test_sdd_fix_docs.py` | extends | add assertions for the new invariants (worktree, no main-checkout branch switch) |
| `scripts/sdd/ensure_worktree.py` | depends on | unchanged; `--brief-key` already accepts a ledger short id |
| `scripts/remove_worktree.py` | depends on | unchanged; its dirty/unpushed refusals become the reap guard |
| `.claude/commands/sdd-brief.md` | modifies (doc only) | Step 12 hand-off made explicit |
| `.claude/rules/worktree-management.md` | modifies | §2 "Created by" list gains `/sdd-fix` (Fast lane) |
| `/sdd-done`, `/sdd-start`, `/sdd-task` | unaffected | no change to their contracts |

No new runtime dependencies; no `parrot.*` package code is touched.

---

## Code Context

### User-Provided Code

None — the user described the behaviour in prose (the Fast lane "creates a branch
in the current worktree, moving the main worktree from dev", and should instead
"run in a worktree, generate a PR to dev and remove the worktree").

### Verified Codebase References

#### The defect (identical text in all three twins)
```text
# .claude/commands/sdd-fix.md:36
# .agents/skills/sdd-fix/SKILL.md:41
# .agent/workflows/sdd-fix.md:40
   - **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev`,
```

#### Classes & Signatures
```python
# From scripts/sdd/brief_meta.py:150
def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:
    ...
    prefix = "hotfix" if base_branch == "main" else "fix"   # line 166
    name = f"{prefix}-{key}-{slug}"                          # line 167
    return WorktreePlan(
        name=name,
        path=f"{WORKTREE_ROOT}/{name}",                      # line 170
        base_ref=f"origin/{base_branch}",                    # line 171
    )

# From scripts/sdd/brief_meta.py:175
def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan:
    ...

# From scripts/sdd/ensure_worktree.py:73
def ensure(
    plan: WorktreePlan,
    *,
    repo_root: Path,
    sync: bool = True,
    require_paths: Sequence[str] = (),
    dry_run: bool = False,
) -> tuple[Path, bool]:
    ...

# From scripts/sdd/ensure_worktree.py:289
def main(argv: Sequence[str] | None = None) -> int:
    ...
```

#### Verified Imports
```python
# scripts/sdd/ensure_worktree.py:44
from scripts.sdd.brief_meta import brief_worktree_plan
# scripts/sdd/ensure_worktree.py:45
from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow
# scripts/sdd/sdd_meta.py:10 — compatibility shim, real home of the parser
from parrot.knowledge.wiki.ledger.sdd_meta import (
    KNOWN_PROJECTS, WORKTREE_ROOT, WorktreePlan, plan_worktree, resolve_flow,
)
```

#### Key Attributes & Constants
- `WORKTREE_ROOT` → `".claude/worktrees"` (`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322`)
- `KNOWN_PROJECTS` includes `sdd-tooling`, `docs`, `ci`, `dev-loop`, `admin-ui` (same file)
- `ensure_worktree` CLI flags (`scripts/sdd/ensure_worktree.py:298-326`):
  `--slug` (required, 298), `--feature-id` (299), `--jira-key` (300),
  `--brief-key` (305 — *"Jira key, ledger short id, or slug … fix-<KEY>-<slug> on --base-branch"*),
  `--spec` (311), `--index` (312), `--base-branch` (313), `--type` (314),
  `--no-sync` (315), `--dry-run` (316), `--json` (317), `--no-native-sync` (318),
  `--no-autobuild` (323)
- `remove_worktree.py` reaper guards: `REFUSED: <n> uncommitted change(s).`
  (`scripts/remove_worktree.py:300`), `REFUSED: <n> commit(s) not on origin.`
  (`:311`), subcommand `remove <target>` with `--stale` / `--delete-branch` /
  `--force` / `--dry-run` (`:406-415`)
- Doc-parity test asserts `"gh pr create --base dev" in docs/sdd/WORKFLOW.md`
  (`tests/sdd/test_sdd_fix_docs.py:25`); the twin-sync test reads
  `.agents/skills/sdd-fix/SKILL.md` and asserts
  `"wikitoolkit ledger plan-fix --json" in fix` (`tests/sdd/test_codex_sdd_sync.py:41,44`)
- Ledger writability from a worktree: the primary checkout's `.parrot/ledger/` is
  mounted writable *"so `wikitoolkit ledger open/claim/close` work from inside a
  worktree"* (`.claude/rules/worktree-management.md:55`)
- `/sdd-brief` already provisions its worktree with
  `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`
  (`.claude/commands/sdd-brief.md`, Step 9)
- `/sdd-done` already removes a finished worktree:
  `git worktree remove "$WORKTREES_DIR/feat-<FEAT-ID>-<slug>"`
  (`.claude/commands/sdd-done.md:870`), and resolves brief keys at `:116-126`

### Does NOT Exist (Anti-Hallucination)
- ~~`scripts/sdd/fix_lane.py`~~ — there is no Fast-lane driver script; the lane
  exists only as prose in the three command/skill/workflow twins. (Option B
  would create it.)
- ~~`ensure_worktree --fix-key`~~ — not a flag. The only brief-ish identity flag
  is `--brief-key` (`ensure_worktree.py:305`); `--feature-id` and `--jira-key`
  are the others.
- ~~`ensure_worktree --recreate`~~ / ~~`--remove`~~ — no such flags; removal is
  `scripts/remove_worktree.py remove` (or `git worktree remove`).
- ~~`scripts/sdd/remove_worktree.py`~~ — the reaper is at the repo-script root,
  `scripts/remove_worktree.py`, not under `scripts/sdd/`.
- ~~a `Fast lane` section in `sdd/WORKFLOW.md`~~ — the string `Fast lane` does
  not appear there; the lane is described in `docs/sdd/WORKFLOW.md:127-135`
  and listed in `docs/sdd/PLATFORM.md:263`.
- ~~`.claude/skills/sdd-fix/SKILL.md`~~ — the Claude surface is
  `.claude/commands/sdd-fix.md`; the `SKILL.md` copy lives under
  `.agents/skills/sdd-fix/` (the Codex surface).
- ~~a `/sdd-fix --worktree` flag~~ — the usage line has only
  `--top`, `--kind`, `--severity`, `--lane` (`.claude/commands/sdd-fix.md:16-20`).

---

## Parallelism Assessment

- **Internal parallelism**: low-to-moderate. The change is small and heavily
  co-edited: the three `/sdd-fix` twins must land together (byte-level parity is
  asserted by tests), so they are one task. A second, independent task can carry
  the surrounding docs (`docs/sdd/WORKFLOW.md`, `docs/sdd/PLATFORM.md`,
  `.claude/rules/worktree-management.md`, the `/sdd-brief` Step 12 wording) and a
  third the test additions in `tests/sdd/test_sdd_fix_docs.py`. Splitting the
  twins across worktrees would guarantee drift.
- **Cross-feature independence**: good, with one caveat. No in-flight spec in
  `sdd/specs/` targets the fix lane (`sdd-fix-ledger-lane.spec.md` is the
  *existing* lane spec, not in flight). The caveat is operational rather than
  textual: this repo runs parallel sessions, and `/sdd-fix` drains are frequent —
  a drain running while this change is in review will still use the old
  main-checkout behaviour. Shared files to watch: the three twins,
  `docs/sdd/WORKFLOW.md`, `tests/sdd/test_sdd_fix_docs.py`.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: the whole change is a few hundred lines of prose across tightly
  coupled twin files plus one test file. The coordination cost of multiple
  worktrees exceeds any parallel gain, and the twin-parity tests punish a split.

---

## Open Questions

- [x] Should `/sdd-brief` also open the PR and reap its worktree? — *Owner: Jesus Lara*: No. Its worktree must survive for implementation (`sdd-worker` runs inside it), so `/sdd-done <KEY>` stays the PR+cleanup owner; this change only makes that hand-off explicit in Step 12.
- [x] Should `/sdd-fix`'s SDD lane also stop committing from the main checkout? — *Owner: Jesus Lara*: No. The spec and tasks must be on `dev` before the worktree is cut from `origin/dev`; the main checkout stays *on* `dev` and only gains commits.
- [x] One worktree per group, or one shared tree for a `--top N` batch? — *Owner: Jesus Lara*: One worktree + one PR per group, created and reaped in sequence.
- [x] What happens to the worktree and the claims on failure? — *Owner: Jesus Lara*: Keep the worktree (report its path), release the claims with `ledger unclaim`.
- [x] Remove the worktree immediately after the PR, or wait for the merge? — *Owner: Jesus Lara*: Remove immediately; the branch is on `origin`, and `ensure_worktree` can re-provision a tree if review feedback arrives.
- [ ] Accept the branch-name change `fix/<id>-<slug>` → `fix-<id>-<slug>`, or add a `--fix-key` alias to `ensure_worktree` that keeps a slashed branch name distinct from the directory name? — *Owner: Jesus Lara*
- [ ] Is prose-only enforcement enough, or should a thin deterministic driver (Option B) land now — at minimum a check that refuses the Fast lane when `git rev-parse --show-toplevel` is the main checkout? — *Owner: Jesus Lara*
- [ ] Should the reaper be invoked as `scripts/remove_worktree.py remove` or as a plain `git worktree remove`? The former brings the dirty/unpushed refusals (desirable) but needs the activated venv; the latter has no guards. — *Owner: Jesus Lara*
- [ ] `/sdd-status` and `/sdd-next` currently reason about `feat-*` / `hotfix-*` trees — do they need to learn about short-lived `fix-*` trees, or is their transience enough reason to leave them out? — *Owner: Jesus Lara*
