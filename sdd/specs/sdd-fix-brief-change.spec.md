---
type: feature
base_branch: dev
projects: [sdd-tooling, docs]
tags: [sdd-fix, fix-lane, worktree, ledger, pull-request]
---

# Feature Specification: Fast lane runs in its own worktree (never the main checkout)

**Feature ID**: FEAT-740
**Date**: 2026-10-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.4

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`/sdd-fix`'s **Fast lane** is specified to work *in the main checkout*:

> `- **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev`, …`
> — `.claude/commands/sdd-fix.md:36`, `.agent/workflows/sdd-fix.md:40`, `.agents/skills/sdd-fix/SKILL.md:41`

That single instruction is the whole defect. Running it:

1. **moves the main checkout off `dev`** onto `fix/<id>-<slug>` and leaves it
   there — every later command in that session (`/sdd-spec`, `/sdd-task`,
   `reserve_ids.py`, a plain `git log`) then resolves against a fix branch
   instead of `dev`;
2. **collides with parallel sessions.** This repo routinely runs several agent
   sessions against the same primary checkout. A `git switch -c` in the shared
   tree re-points *their* `HEAD` too: their commits land on the fix branch, and
   an unrelated session's `reset --hard origin/dev` can eat the fix. The rule
   that forbids exactly this already exists for every other lane
   (`.claude/rules/worktree-management.md`: *all feature edits happen inside
   `<path>` — never in the primary checkout*);
3. **requires a clean checkout** as a precondition
   (`.claude/commands/sdd-fix.md:34`), so the lane refuses to run whenever the
   main tree holds any unrelated edit — a frequent and pointless block;
4. **leaves the branch behind**: there is no cleanup step at all, so after the
   PR is opened the main checkout is still sitting on the fix branch.

The fix lane is the highest-frequency SDD entry point — `sdd/specs/` holds 20+
`fixgroup-*.spec.md` specs from past drains — so the cost of "it mutates the
shared tree" is paid repeatedly.

### Goals

- G1. A Fast-lane fix never changes the main checkout's branch and never
  requires the main checkout to be clean.
- G2. A Fast-lane group completes end-to-end inside one `/sdd-fix` run:
  worktree → edit → test → commit → push → PR to `dev` → worktree removed.
- G3. One worktree and one PR **per group**, so each group stays independently
  reviewable and revertable.
- G4. On failure the work is preserved and the issues are returned to the
  ledger — never silently claimed, never silently discarded.
- G5. Reuse the existing provisioning and reaping CLIs; add no new Python.

### Non-Goals (explicitly out of scope)

- **`/sdd-brief` keeps its current shape.** It already provisions a worktree
  (`.claude/commands/sdd-brief.md` Step 9) and must *keep* it, because
  implementation happens inside it (`cd <wt> && claude --agent sdd-worker`);
  a PR can only exist after the code does, which is `/sdd-done <KEY>`'s job
  (`.claude/commands/sdd-done.md:116-126`, `:868-870`). The only brief-side
  change here is one sentence making that hand-off impossible to miss.
- **`/sdd-fix`'s SDD lane keeps its current shape.** The FEAT-ID reservation
  and the spec/task commits stay in the main checkout on `dev`, because the
  worktree is cut from `origin/dev` and must find the spec and index already
  there. That lane does not change the main checkout's branch — it only adds
  commits to `dev`.
- **No runtime enforcement.** A guard script that refuses when the lane runs in
  the main checkout was considered and rejected (see §8 Q2): the defect is the
  instruction itself, not an agent disobeying a correct instruction.
- **No new test code.** Deliberate ("prose only"); the existing twin-parity and
  docs-parity suites are the regression gate. See §8 Q2.
- Runtime-driver alternatives (a `scripts/sdd/fix_lane.py` owning the lane as
  tested Python) were rejected in brainstorm — see
  `sdd/proposals/sdd-fix-brief-change.brainstorm.md` Option B.

---

## 2. Architectural Design

### Overview

Replace the Fast lane's bespoke main-checkout branching with the worktree
provisioning the rest of SDD already uses, and reap the tree with the reaper
the rest of SDD already uses. This is a **documentation change to one canonical
procedure** plus its surrounding policy docs — no package code is touched.

The enabling fact is that the needed worktree plan already exists.
`scripts/sdd/brief_meta.py:150` `brief_worktree_plan()` computes
`prefix = "hotfix" if base_branch == "main" else "fix"` (line 166) and
`name = f"{prefix}-{key}-{slug}"` (line 167), so with a non-`main` base it
yields exactly `.claude/worktrees/fix-<key>-<slug>` based on `origin/dev`.
`ensure_worktree`'s `--brief-key` is documented to accept a "Jira key, **ledger
short id**, or slug" (`scripts/sdd/ensure_worktree.py:305-310`) — a ledger short
id is precisely the Fast lane's identity, and it satisfies
`_SAFE_REF_RE = ^[A-Za-z0-9][A-Za-z0-9._-]*$` (`brief_meta.py:28`).

So the new Fast lane, per group, is six calls to existing tooling:

1. `python -m scripts.sdd.ensure_worktree --json --slug <suggested_slug> --brief-key <issue-short-id> --base-branch dev` → `<wt>`
2. edit inside `<wt>`; tests from `<wt>` with `PYTHONPATH=packages/<dist>/src`; `ruff check --fix`
3. `git -C <wt> add <files> && git -C <wt> commit`
4. `git -C <wt> push -u origin fix-<issue-short-id>-<suggested_slug>`
5. `gh pr create --base dev …` (always; no direct-push path)
6. close the issues, then `python scripts/remove_worktree.py remove fix-<issue-short-id>-<suggested_slug>`

Three properties come for free from the reused tooling rather than from prose:
`ensure_worktree` clears the auto-set upstream so step 4's `-u` is a deliberate
first push; it syncs the gitignored native `.so` artifacts into the tree
(FEAT-722) so step 2's tests can import the Cython modules; and
`remove_worktree.py` refuses to remove a tree with uncommitted changes
(`scripts/remove_worktree.py:300`) or with commits `origin` does not have
(`:311`) — which *is* the "never reap before the push landed" invariant.

**Branch naming changes** from `fix/<id>-<slug>` to `fix-<id>-<slug>`: a git
worktree directory name cannot carry the `/`, and the branch now doubles as the
directory name. Accepted (§8 Q1) because it makes the lane visible in
`git worktree list` and `/sdd-status`.

### Component Diagram

```
/sdd-fix  (main checkout: NEVER changes branch, NEVER needs to be clean)
  │
  ├─ 1 plan ── wikitoolkit ledger plan-fix --json        (unchanged)
  ├─ 2 select                                            (unchanged)
  ├─ 3 claim ── wikitoolkit ledger claim                 (unchanged)
  ├─ 4 prime ── wikitoolkit ledger context --max-tokens 3000   (unchanged)
  │
  ├─ 5 route ─┬─ FAST lane  (CHANGED — per group)
  │           │    ensure_worktree --brief-key <id> --base-branch dev
  │           │        └─► .claude/worktrees/fix-<id>-<slug>  (from origin/dev)
  │           │    edit · pytest (PYTHONPATH=…) · ruff · commit · push -u
  │           │    gh pr create --base dev
  │           │    remove_worktree.py remove fix-<id>-<slug>   (no --force)
  │           │
  │           └─ SDD lane   (unchanged: spec+tasks on dev, worktree, /sdd-done)
  │
  ├─ 6 close ── ledger close --resolved-by commit:<sha>   (diff read from <wt>)
  └─ 7 release ─ ledger unclaim   (+ NEW: fast-lane failure keeps <wt>)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts.sdd.ensure_worktree` | uses (unchanged) | `--brief-key <short-id> --base-branch dev` → `fix-<id>-<slug>`; `--json` returns the path |
| `scripts/sdd/brief_meta.py` | uses (unchanged) | `brief_worktree_plan()` already yields the `fix-` prefix off a non-`main` base |
| `scripts/remove_worktree.py` | uses (unchanged) | `remove <target>`; its dirty/unpushed refusals become the reap guard |
| `wikitoolkit ledger` | uses (unchanged) | plan-fix / claim / close / unclaim; resolves to the main checkout, writable from a worktree |
| `gh` CLI | uses (unchanged) | `gh pr create --base dev`, always |
| `/sdd-done` | unaffected | still the PR+cleanup owner for the SDD lane and for briefs |
| `/sdd-brief` | doc-only | one sentence added to Step 12's hand-off |
| `.claude/rules/worktree-management.md` | modifies | §2's "Created by" list gains `/sdd-fix` (Fast lane) |

### Data Models

None — no code, no new models. The only structured artifact consumed is the
existing `FixPlan` JSON from `wikitoolkit ledger plan-fix --json`
(`planner_version == "1"`, already contracted in Step 1).

### New Public Interfaces

None. No new CLI flags, no new scripts, no new Python symbols. The change is
confined to the canonical `/sdd-fix` procedure text and its policy docs.

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `/sdd-fix` canonical procedure | yes | Exact replacement text fixed in the Interface Skeleton below; must be byte-identical across the three twins (`$sdd-` ↔ `/sdd-` only) | — |
| M2: Policy docs | yes | Four one-line edits, exact text below; forbidden/required tokens enumerated | — |
| M3: `/sdd-brief` hand-off | yes | One sentence in the Claude file + the mechanical agy re-derivation the test specifies | — |

### Module 1: `/sdd-fix` canonical procedure — Fast lane and Release rule
- **Path**: `.claude/commands/sdd-fix.md`, `.agent/workflows/sdd-fix.md`,
  `.agents/skills/sdd-fix/SKILL.md`
- **Responsibility**: Replace Step 5's main-checkout branching with worktree
  provisioning, add the reap step, and add the Fast-lane failure rule to Step 7.
- **Depends on**: nothing in this spec.
- **CRITICAL constraint**: `tests/sdd/test_ledger_workflow_twins.py`
  `TestFixTwins.test_complete_procedure_is_identical_across_hosts` strips the
  frontmatter and the first body line, maps `$sdd-` → `/sdd-`, and asserts the
  three bodies are **equal**. Edit all three identically or the suite fails.
- **Interface Skeleton** *(verbatim replacement text — the "signature" of a doc module)*:
  ```text
  # modifies .claude/commands/sdd-fix.md:33-38 (verified) and the same block in both twins
  #   .agent/workflows/sdd-fix.md:37-42 · .agents/skills/sdd-fix/SKILL.md:38-43
  5. **Route** by `group.lane`:
     - NEVER switch the main checkout's branch and never require it to be clean; every lane
       works inside a worktree provisioned by `python -m scripts.sdd.ensure_worktree`.
       If execution cannot proceed, release successful claims in step 7.
     - **Fast lane** (`lane == "fast"`): one worktree and one PR per group.
       `python -m scripts.sdd.ensure_worktree --json --slug <suggested_slug> --brief-key <issue-short-id> --base-branch dev`
       plans `fix-<issue-short-id>-<suggested_slug>` off `origin/dev` and returns `<wt>`;
       `--base-branch dev` is what selects the `fix-` prefix. Edit inside `<wt>`, run the affected
       package's tests from `<wt>` with `PYTHONPATH=packages/<dist>/src` (a bare `pytest` there
       imports the main checkout), `ruff check --fix` the changed files, `git -C <wt> commit`,
       `git -C <wt> push -u origin fix-<issue-short-id>-<suggested_slug>` (the tree has no
       upstream by design), then `gh pr create --base dev --title … --body …`.
       ALWAYS a PR — there is no direct-push path. Once step 6 has closed the group's issues, reap
       the tree: `python scripts/remove_worktree.py remove fix-<issue-short-id>-<suggested_slug>`
       — never `--force`, never `--delete-branch` (the PR needs the remote branch). A refusal
       means something is uncommitted or unpushed: keep the tree and report it.

  # appended to step 7, after the SDD-lane hand-off paragraph
  #   modifies .claude/commands/sdd-fix.md:54-60 (verified) and the same block in both twins
     **Fast-lane failure**: when tests, commit, push or `gh pr create` fails, KEEP the worktree,
     report its path, and unclaim every issue claimed for that group. Never reap a tree whose
     work is not on origin, and never force-push to rescue a rejected push.
  ```
- **Token invariants the existing suite enforces** (keep / avoid):
  keep `gh pr create --base dev`, `ledger plan-fix --json`, `ledger claim`,
  `ledger unclaim`, `ledger close`, `--resolved-by`, `two keys`, `parents`,
  `reserve_ids`, `ensure_worktree`, `ledger context`, `--max-tokens 3000`,
  `shared ledger is read-only`, `worktree-local ledger`, `Fast lane`,
  `SDD lane`, `--lane`; never introduce `git push origin dev`, `--no-pr`,
  or `ledger acknowledge`.

### Module 2: Surrounding policy docs
- **Path**: `docs/sdd/WORKFLOW.md`, `docs/sdd/PLATFORM.md`,
  `.claude/rules/worktree-management.md`, `.agent/skills/worktree-management/SKILL.md`
- **Responsibility**: Make the four places that describe the lane agree with M1.
- **Depends on**: nothing (disjoint file set from M1 and M3); wording is fixed
  by this spec, not derived from M1 at implementation time.
- **Interface Skeleton**:
  ```text
  # modifies docs/sdd/WORKFLOW.md:134 (verified)
  through the **Fast lane** (worktree `fix-<id>-<slug>` off `origin/dev`, always
  `gh pr create --base dev`, worktree reaped after the PR).

  # modifies docs/sdd/PLATFORM.md:263 (verified)
  | `/sdd-fix [issue-id]` | Ledger-driven fix lane: `ledger plan-fix --json` → claim → Fast lane
  (worktree + PR + reap, one per group) or SDD lane (spec/tasks/worktree) → close with
  `--resolved-by` → `unclaim` the rest. |

  # modifies .claude/rules/worktree-management.md:32 (verified)
  #   and .agent/skills/worktree-management/SKILL.md:30 (verified) — same line, keep them in sync
  - Created by whoever implements: `/sdd-start`, `sdd-worker`, `/sdd-fix` (Fast lane, via
    `--brief-key <ledger-short-id> --base-branch dev`), and the dev-loop orchestrators
    (`sdd-planner`, `sdd-research`, `sdd-autopilot`). `/sdd-task` creates none (FEAT-552).
  ```
- **Token invariants** (`tests/sdd_scripts/test_pr_policy_wording_contract.py`):
  `.claude/rules/worktree-management.md` must keep `--brief-key` and
  `clears the auto-set upstream`; all four docs in `_DOCS` must keep
  `merges into `main`` or `merge into `main``, must not contain
  `opens a PR against `main``, `/sdd-spec --type hotfix`, or `type: hotfix`.
  `docs/sdd/WORKFLOW.md` must keep the literal `gh pr create --base dev`
  (`tests/sdd/test_sdd_fix_docs.py:25`) and a `| `/sdd-brief` row.

### Module 3: `/sdd-brief` hand-off clarity
- **Path**: `.claude/commands/sdd-brief.md`, `.agent/workflows/sdd-brief.md`
- **Responsibility**: State in Step 12 that `/sdd-done <KEY>` is what opens the
  PR and removes the brief worktree — the brief lane deliberately does neither.
- **Depends on**: nothing (disjoint file set).
- **CRITICAL constraint**: `tests/sdd_scripts/test_sdd_brief_twin_contract.py`
  `test_agy_preserves_full_procedure_with_native_handoff` asserts the agy twin's
  body equals the Claude file with exactly two string replacements (the two
  `claude --agent sdd-worker` launch forms). So the agy twin is **re-derived**,
  not hand-edited, and must never contain `claude --agent`.
  `.agents/skills/sdd-brief/SKILL.md` is a condensed twin checked only for
  shared tokens and `$sdd-done <KEY>`; it needs no change.
- **Interface Skeleton**:
  ```text
  # modifies .claude/commands/sdd-brief.md:179 (verified) — replaces that one line
  Finish by directing the owner to run `/sdd-done <KEY>` after implementation: it verifies the
  brief's tasks, opens the PR against `base_branch`, and removes this worktree. `/sdd-brief`
  itself opens no PR and removes nothing — the worktree must survive for implementation.

  # .agent/workflows/sdd-brief.md — re-derive from the Claude file with the two replacements
  #   the test specifies; do not hand-edit (verified: tests/sdd_scripts/test_sdd_brief_twin_contract.py:38-52)
  ```

---

## 4. Test Specification

### Unit Tests

No new tests (decision §8 Q2 — "prose only"). The existing suites already
assert the invariants this change must not break:

| Test | Module | Description |
|---|---|---|
| `TestFixTwins::test_complete_procedure_is_identical_across_hosts` | M1 | The three twin bodies stay byte-identical after the edit |
| `TestFixTwins::test_all_twins_require_a_pr_on_the_fast_lane` | M1 | `gh pr create --base dev` kept; `git push origin dev` / `--no-pr` absent |
| `TestFixTwins::test_all_twins_document_both_lanes` | M1 | `Fast lane`, `SDD lane`, `--lane` still present |
| `TestFixTwins::test_all_twins_release_unfixed_issues` | M1 | `ledger claim` / `ledger unclaim` still present |
| `TestFixTwins::test_read_only_ledger_exits_without_claiming` | M1 | `shared ledger is read-only`, `ledger context`, `--max-tokens 3000` kept |
| `TestFixTwins::test_all_twins_reuse_open_parent_or_mint` | M1 | `parents`, `reserve_ids`, `ensure_worktree` still present |
| `test_workflow_doc_has_fix_lane_section` | M2 | `docs/sdd/WORKFLOW.md` keeps the lane section and `gh pr create --base dev` |
| `test_worktree_rule_documents_brief_key` | M2 | `--brief-key` and `clears the auto-set upstream` survive the rule edit |
| `test_old_rule_gone` / `test_docs_state_never_merges_into_main` | M2 | `main`-PR wording unchanged in all four policy docs |
| `test_agy_preserves_full_procedure_with_native_handoff` | M3 | agy brief twin is exactly the Claude text with the two launch replacements |
| `test_codex_handoff_stays_in_codex` | M3 | codex brief twin keeps `$sdd-done <KEY>` and no `claude --agent` |
| `test_existing_codex_workflow_skills_retain_shared_lifecycle_contracts` | M1 | `.agents/skills/sdd-fix/SKILL.md` keeps `wikitoolkit ledger plan-fix --json` |

### Integration Tests

| Test | Description |
|---|---|
| `tests/sdd/test_ledger_workflow_twins.py` | Whole-file run: twin parity across every SDD command, including the three `/sdd-fix` twins this feature edits |
| `tests/sdd_scripts/test_pr_policy_wording_contract.py` | Whole-file run: the FEAT-698 PR rule across `CLAUDE.md`, both `WORKFLOW.md`s and the worktree rule |

A real end-to-end drain (`/sdd-fix` against a live ledger issue) is **manual
acceptance**, not an automated test: it requires a claimable ledger issue, a
push and a GitHub PR. See §5 AC-10.

### Validation Contract

tests:
- tests/sdd/test_ledger_workflow_twins.py
- tests/sdd/test_sdd_fix_docs.py
- tests/sdd/test_codex_sdd_sync.py
- tests/sdd_scripts/test_pr_policy_wording_contract.py
- tests/sdd_scripts/test_sdd_brief_twin_contract.py
- tests/sdd_scripts/test_sdd_brief_command_contract.py
- tests/sdd_scripts/test_command_contracts.py
- tests/sdd_scripts/test_feat722_doc_contract.py
markers: none

### Test Data / Fixtures

None — every test above reads repository files from disk via
`Path(__file__).resolve().parents[2]` (never the process CWD, because importing
`parrot` chdirs to the main checkout; see the comment at
`tests/sdd/test_ledger_workflow_twins.py:19-26`).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1 (G1).** No `/sdd-fix` twin instructs a main-checkout branch switch:
      `grep -lF 'in the MAIN checkout (no worktree)' .claude/commands/sdd-fix.md .agent/workflows/sdd-fix.md .agents/skills/sdd-fix/SKILL.md`
      prints nothing, and `grep -cF 'require a clean checkout' ` is `0` in all three.
- [ ] **AC-2 (G1, G5).** All three twins instruct
      `scripts.sdd.ensure_worktree --json --slug <suggested_slug> --brief-key <issue-short-id> --base-branch dev`
      in the Fast lane (`grep -cF '--brief-key <issue-short-id> --base-branch dev'` is `1` in each).
- [ ] **AC-3 (G2).** All three twins instruct
      `python scripts/remove_worktree.py remove fix-<issue-short-id>-<suggested_slug>`
      and state `never --force, never --delete-branch` on that step.
- [ ] **AC-4 (G3).** All three twins say "one worktree and one PR per group".
- [ ] **AC-5 (G4).** All three twins carry the **Fast-lane failure** rule: keep
      the worktree, report its path, unclaim the group's issues.
- [ ] **AC-6.** All three twins instruct the in-worktree test prefix
      `PYTHONPATH=packages/<dist>/src` for the Fast lane.
- [ ] **AC-7.** `TestFixTwins::test_complete_procedure_is_identical_across_hosts`
      passes — the three bodies are still byte-identical.
- [ ] **AC-8 (M2).** `docs/sdd/WORKFLOW.md`, `docs/sdd/PLATFORM.md`,
      `.claude/rules/worktree-management.md` and
      `.agent/skills/worktree-management/SKILL.md` describe the Fast lane as a
      worktree lane, and the worktree rule lists `/sdd-fix` among the creators.
- [ ] **AC-9 (M3).** `/sdd-brief` Step 12 states that `/sdd-done <KEY>` opens the
      PR and removes the worktree, and the agy twin is the re-derived copy
      (contains no `claude --agent`).
- [ ] **AC-10.** Every file in the §4 Validation Contract passes:
      `pytest tests/sdd/test_ledger_workflow_twins.py tests/sdd/test_sdd_fix_docs.py tests/sdd/test_codex_sdd_sync.py tests/sdd_scripts/test_pr_policy_wording_contract.py tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`
- [ ] **AC-11.** No `parrot.*` package code and no file under `scripts/` is
      modified by this feature (`git diff --name-only origin/dev...HEAD` lists
      only the nine doc files of M1–M3).
- [ ] **AC-12.** No breaking change to existing public API (vacuous — no code
      changes), and no new external dependency.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from scripts.sdd.brief_meta import brief_worktree_plan            # verified: scripts/sdd/ensure_worktree.py:44
from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # verified: scripts/sdd/ensure_worktree.py:45
from parrot.knowledge.wiki.ledger.sdd_meta import (               # verified: scripts/sdd/sdd_meta.py:10
    KNOWN_PROJECTS, WORKTREE_ROOT, WorktreePlan, plan_worktree, resolve_flow,
)
```

### Existing Class Signatures

```python
# scripts/sdd/brief_meta.py
BRIEFS_DIR: str = "sdd/briefs"                                       # line 22
BRIEF_BASE_BRANCHES: frozenset[str] = frozenset({"main", "dev", "staging"})  # line 27
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")           # line 28

def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:  # line 150
    prefix = "hotfix" if base_branch == "main" else "fix"            # line 166
    name = f"{prefix}-{key}-{slug}"                                  # line 167
    return WorktreePlan(
        name=name,                                                   # line 169
        path=f"{WORKTREE_ROOT}/{name}",                              # line 170
        base_ref=f"origin/{base_branch}",                            # line 171
    )

def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan: ...        # line 175

# scripts/sdd/ensure_worktree.py
def ensure(                                                          # line 73
    plan: WorktreePlan,
    *,
    repo_root: Path,
    sync: bool = True,
    require_paths: Sequence[str] = (),
    dry_run: bool = False,
) -> tuple[Path, bool]: ...
def main(argv: Sequence[str] | None = None) -> int: ...              # line 289

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
WORKTREE_ROOT: str = ".claude/worktrees"                             # line 322
```

### Key Attributes & Constants

- `ensure_worktree` CLI flags (`scripts/sdd/ensure_worktree.py:298-326`):
  `--slug` (298, required), `--feature-id` (299), `--jira-key` (300),
  **`--brief-key` (305** — help text: *"Brief identity (FEAT-698 /sdd-brief):
  Jira key, ledger short id, or slug. Plans hotfix-<KEY>-<slug> on main
  (default) or fix-<KEY>-<slug> on --base-branch; mutually exclusive with
  --feature-id, --jira-key and --type."*), `--spec` (311), `--index` (312),
  `--base-branch` (313), `--type` (314), `--no-sync` (315), `--dry-run` (316),
  `--json` (317), `--no-native-sync` (318), `--no-autobuild` (323)
- `scripts/remove_worktree.py`: subcommand `remove <target>` (405) with `--stale`
  (408), `--delete-branch` (410), `--force` (412), `--dry-run` (415); refusals
  `REFUSED: <n> uncommitted change(s).` (300) and
  `REFUSED: <n> commit(s) not on origin.` (311); `list` subcommand at 400 with
  `LIVE(n)` / `dirty:n` / `unpushed:n` flags (222-228)
- Ledger writability from inside a worktree: the primary checkout's
  `.parrot/ledger/` is mounted writable *"so `wikitoolkit ledger
  open/claim/close` work from inside a worktree"*
  (`.claude/rules/worktree-management.md:55`)
- The ledger resolves to the main checkout, and a read-only ledger exits
  without claiming (`.claude/commands/sdd-fix.md:9-11`)
- `/sdd-brief` already provisions its worktree with
  `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`
  (`.claude/commands/sdd-brief.md` Step 9)
- `/sdd-done` removes the finished worktree with
  `git worktree remove "$WORKTREES_DIR/feat-<FEAT-ID>-<slug>"`
  (`.claude/commands/sdd-done.md:870`) and resolves brief keys at `:116-126`
- `KNOWN_PROJECTS` includes `sdd-tooling` and `docs`
  (`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`)

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Fast-lane provisioning step | `ensure_worktree --brief-key` | CLI call | `scripts/sdd/ensure_worktree.py:305` |
| `fix-<id>-<slug>` naming | `brief_worktree_plan()` prefix rule | computed from `--base-branch dev` | `scripts/sdd/brief_meta.py:166-167` |
| Fast-lane reap step | `scripts/remove_worktree.py remove` | CLI call | `scripts/remove_worktree.py:405` |
| Reap guard (no `--force`) | dirty / unpushed refusals | exit before removal | `scripts/remove_worktree.py:300,311` |
| Twin parity gate | `TestFixTwins` | pytest assertion on file bodies | `tests/sdd/test_ledger_workflow_twins.py:196-206` |
| Brief twin derivation | `test_agy_preserves_full_procedure_with_native_handoff` | pytest string-replacement equality | `tests/sdd_scripts/test_sdd_brief_twin_contract.py:38-52` |

### Does NOT Exist (Anti-Hallucination)

- ~~`scripts/sdd/fix_lane.py`~~ — there is no Fast-lane driver script; the lane
  exists only as prose in the three twins.
- ~~`ensure_worktree --fix-key`~~ — not a flag. The identity flags are
  `--feature-id`, `--jira-key` and `--brief-key` only
  (`scripts/sdd/ensure_worktree.py:299-310`).
- ~~`ensure_worktree --recreate`~~ / ~~`ensure_worktree --remove`~~ — no such
  flags; removal is `scripts/remove_worktree.py remove` or `git worktree remove`.
- ~~`scripts/sdd/remove_worktree.py`~~ — the reaper lives at the scripts root,
  `scripts/remove_worktree.py`, NOT under `scripts/sdd/`.
- ~~a `Fast lane` section in `sdd/WORKFLOW.md`~~ — the string does not appear
  there; the lane is documented in `docs/sdd/WORKFLOW.md:127-135` and listed in
  `docs/sdd/PLATFORM.md:263`.
- ~~`.claude/skills/sdd-fix/SKILL.md`~~ — the Claude surface is
  `.claude/commands/sdd-fix.md`; the `SKILL.md` copy is the Codex surface under
  `.agents/skills/sdd-fix/`.
- ~~`.agent/rules/worktree-management.md`~~ — does not exist. The twin of
  `.claude/rules/worktree-management.md` is
  `.agent/skills/worktree-management/SKILL.md`.
- ~~a `/sdd-fix --worktree` flag~~ — the usage line has only `--top`, `--kind`,
  `--severity`, `--lane` (`.claude/commands/sdd-fix.md:14-17`).
- ~~a `### 12. Hand Off` section in `.agents/skills/sdd-brief/SKILL.md`~~ — the
  codex brief twin is condensed and has no such section.

### Edit Sites (Blueprint Anchors)

<!-- Verified against: 87341f43c (`git rev-parse --short HEAD` at spec time).
     `/sdd-task` MUST re-run `grep -c` for every row it uses — this table saves
     the search, not the check. -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `.claude/commands/sdd-fix.md` | MODIFY | `   - Before changing branches, require a clean checkout; never carry unrelated changes into a fix.` | `sdd-fix.md:34` | 1 |
| `.claude/commands/sdd-fix.md` | MODIFY | `   - **Fast lane** (\`lane == "fast"\`): in the MAIN checkout (no worktree), \`git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev\`,` | `sdd-fix.md:36` | 1 |
| `.claude/commands/sdd-fix.md` | MODIFY | `7. **Release** — every claimed issue that failed either key: \`wikitoolkit ledger unclaim <issue-id> --reason "<why>" --actor agent:sdd-fix\`.` | `sdd-fix.md:54` | 1 |
| `.agent/workflows/sdd-fix.md` | MODIFY | same three anchors as above | `:38`, `:40`, `:58` | 1 each |
| `.agents/skills/sdd-fix/SKILL.md` | MODIFY | same three anchors as above | `:39`, `:41`, `:59` | 1 each |
| `docs/sdd/WORKFLOW.md` | MODIFY | ``through the **Fast lane** (branch `fix/<id>-<slug>` off `origin/dev`, always`` | `WORKFLOW.md:134` | 1 |
| `docs/sdd/PLATFORM.md` | MODIFY | ``| `/sdd-fix [issue-id]` | Ledger-driven fix lane: `ledger plan-fix --json` → claim → Fast lane (branch + PR) or SDD lane (spec/tasks/worktree) → close with `--resolved-by` → `unclaim` the rest. |`` | `PLATFORM.md:263` | 1 |
| `.claude/rules/worktree-management.md` | MODIFY | ``- Created by whoever implements: `/sdd-start`, `sdd-worker`, and the dev-loop orchestrators (`sdd-planner`, `sdd-research`, `sdd-autopilot`). `/sdd-task` creates none (FEAT-552).`` | `worktree-management.md:32` | 1 |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | same anchor as above | `SKILL.md:30` | 1 |
| `.claude/commands/sdd-brief.md` | MODIFY | ``Finish by directing the owner to run `/sdd-done <KEY>` after implementation.`` | `sdd-brief.md:179` | 1 |
| `.agent/workflows/sdd-brief.md` | MODIFY | same anchor as above — but **re-derive the whole file** from the Claude twin per the test's two replacements, do not hand-edit | `sdd-brief.md:183` | 1 |

- Every anchor's occurrence count is 1, so no surrounding context is required.
- No CREATE rows: this feature adds no files.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **One canonical procedure, three surfaces.** Write the Fast-lane text once,
  then apply it byte-identically to `.claude/commands/sdd-fix.md`,
  `.agent/workflows/sdd-fix.md` and `.agents/skills/sdd-fix/SKILL.md`. The
  only permitted differences are the frontmatter, the first body line (title)
  and `$sdd-` vs `/sdd-` — anything else fails `TestFixTwins`.
- **Never hand-roll `git worktree add`** and never use `claude --worktree`;
  provisioning goes only through `scripts.sdd.ensure_worktree`
  (`.claude/rules/worktree-management.md` §2).
- Match the surrounding doc style: numbered steps, bold step names, inline
  backticked commands, two-space continuation indent inside a bullet.
- Keep the diff minimal — nine files, no code, no refactors.

### Known Risks / Gotchas

- **`--base-branch dev` is load-bearing.** Omit it and
  `brief_worktree_plan()` defaults to the `hotfix-` prefix on `main`
  (`brief_meta.py:166`) — the lane would branch off `main`. The flag is not
  optional decoration.
- **A bare `pytest` inside a worktree is a false result.** The shared `.venv`
  is editable-installed against the main checkout, so the Fast lane's tests
  must carry `PYTHONPATH=packages/<dist>/src`, one entry per changed package
  (`.claude/rules/worktree-management.md` §4).
- **Never `uv sync` or `maturin develop` inside the worktree** — it re-points
  the shared venv's `.pth` and breaks `import parrot` for every session,
  including after the worktree is removed.
- **Never pass `--force` to the reaper.** Its dirty/unpushed refusals are the
  safety property this design relies on; forcing past them discards work that
  `origin` does not have.
- **Never `--delete-branch`**: the open PR needs the remote branch.
- **`gh pr create` failure is recoverable, not fatal.** The branch is already
  pushed, so the lane reports the exact command and keeps the tree.
- **Removing the worktree immediately** means no local tree for review
  feedback; `ensure_worktree` is idempotent, so a tree can be re-provisioned on
  the same branch when comments arrive (resolved §8 Q5 of the brainstorm).
- **The ledger still lives in the main checkout.** Claims and closes from inside
  `<wt>` work because `.parrot/ledger/` is mounted writable; a read-only ledger
  still exits without claiming, before any worktree is created.
- **Per-group cost.** Each group now pays a worktree checkout plus a native
  artifact sync where it previously paid nothing. Accepted for correctness.
- **Operational overlap.** A `/sdd-fix` drain started before this change lands
  still uses the old main-checkout behaviour; there is no migration, the next
  run simply reads the new text.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None. No new runtime or dev dependency; `gh` and `git` are already required by the lane. |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Should `/sdd-brief` also open the PR and reap its worktree? — *Resolved in brainstorm*: No. Its worktree must survive for implementation (`sdd-worker` runs inside it), so `/sdd-done <KEY>` stays the PR+cleanup owner; this change only makes that hand-off explicit in Step 12 (M3).
- [x] Should `/sdd-fix`'s SDD lane also stop committing from the main checkout? — *Resolved in brainstorm*: No. The spec and tasks must be on `dev` before the worktree is cut from `origin/dev`; the main checkout stays *on* `dev` and only gains commits. §1 Non-Goals.
- [x] One worktree per group, or one shared tree for a `--top N` batch? — *Resolved in brainstorm*: One worktree + one PR per group, created and reaped in sequence. §2, AC-4.
- [x] What happens to the worktree and the claims on failure? — *Resolved in brainstorm*: Keep the worktree (report its path), release the claims with `ledger unclaim`. M1 Step 7 rule, AC-5.
- [x] Remove the worktree immediately after the PR, or wait for the merge? — *Resolved in brainstorm*: Remove immediately; the branch is on `origin` and `ensure_worktree` can re-provision a tree if review feedback arrives. §7 Known Risks.
- [x] **Q1.** Accept the branch-name change `fix/<id>-<slug>` → `fix-<id>-<slug>`, or add a `--fix-key` alias keeping a slashed branch name? — *Resolved 2026-10-24*: Accept `fix-<id>-<slug>`. A worktree directory name cannot contain `/`, `brief_meta.py:166-167` already produces this name, and no new CLI surface is needed. `docs/sdd/WORKFLOW.md:134` is updated with it (M2).
- [x] **Q2.** Is prose-only enforcement enough, or should a runtime guard / new doc-parity assertion land now? — *Resolved 2026-10-24*: Prose only. The defect is the instruction itself, so correcting the text fixes the behaviour; the existing twin-parity suites catch drift. No new test code, no guard script. §1 Non-Goals.
- [x] **Q3.** `scripts/remove_worktree.py remove` or a plain `git worktree remove`? — *Resolved 2026-10-24*: `scripts/remove_worktree.py remove`, for its dirty/unpushed refusals (`:300`, `:311`). It needs the activated venv, which an interactive `/sdd-fix` run already has.
- [ ] **Q4.** Should `/sdd-status` and `/sdd-next` learn about short-lived `fix-*` worktrees, or is their transience reason enough to leave them out? — *Owner: Jesus Lara* (deferrable: does not block M1–M3).
- [ ] **Q5.** Should the brainstorm be marked `accepted` and the `codex` design-research seat (§9) run before implementation starts? It was skipped only because the brainstorm is still `exploration`. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec).
> Model: `n/a` · Status: **skipped** (exploration doc
> `sdd/proposals/sdd-fix-brief-change.brainstorm.md` has `**Status**:
> exploration`, not `accepted` — §3b precondition not met; `codex-cli 0.163.0`
> *was* available) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

To run it: mark the brainstorm `**Status**: accepted` and re-run `/sdd-spec
sdd-fix-brief-change` (see §8 Q5).

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec —
  `.claude/worktrees/feat-FEAT-740-sdd-fix-brief-change`, provisioned with
  `python -m scripts.sdd.ensure_worktree --slug sdd-fix-brief-change --feature-id FEAT-740`
  (base `origin/dev`). The `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**: **no edges.** M1, M2 and M3 touch disjoint file
  sets (M1: the three `sdd-fix` surfaces · M2: `docs/sdd/WORKFLOW.md`,
  `docs/sdd/PLATFORM.md`, the two `worktree-management` copies · M3: the two
  `sdd-brief` surfaces), and every wording decision is fixed by this spec rather
  than derived from a sibling module at implementation time. All three are
  expected to run concurrently.
- **Shared files**: none. No file appears in more than one module, so no task
  needs serializing for write contention.
- **Exclusive resources**: none. No extension rebuild, no lockfile, no
  migration, no shared state outside the modules' own files — every task is
  `parallel: true`.
- **Intra-module coupling (not a graph edge, but a task-boundary rule)**: the
  three `sdd-fix` twins MUST be edited in one task (byte-identical bodies are
  asserted by `TestFixTwins::test_complete_procedure_is_identical_across_hosts`),
  and the two `sdd-brief` surfaces MUST be edited in one task (the agy twin is a
  mechanical re-derivation of the Claude twin, asserted by
  `test_agy_preserves_full_procedure_with_native_handoff`). Splitting either
  pair across tasks guarantees a red suite at the merge gate.
- **Cross-feature dependencies**: none — no in-flight spec in `sdd/specs/`
  targets the fix lane (`sdd-fix-ledger-lane.spec.md` is the lane's existing,
  already-merged spec). Operational note only: a `/sdd-fix` drain running while
  this change is in review still follows the old main-checkout text.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-24 | Jesus Lara | Initial draft from `sdd/proposals/sdd-fix-brief-change.brainstorm.md` (Option A) |
| 0.2 | 2026-10-24 | Jesus Lara | Approved for decomposition |
| 0.3 | 2026-10-24 | Jesus Lara | Validation Contract += test_sdd_brief_command_contract, test_command_contracts, test_feat722_doc_contract (found reading the edited files during /sdd-task) |
