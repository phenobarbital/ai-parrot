---
type: feature
base_branch: dev
---

# Feature Specification: Worktree Creation Ownership

**Feature ID**: FEAT-552
**Date**: 2026-09-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`/sdd-task` creates the feature worktree **eagerly**, at planning time
(`.claude/commands/sdd-task.md:313`, §6), immediately after committing the
task files to `base_branch`. That couples two things that do not belong
together:

- **TASK files and the per-spec index are versioned state.** They are
  committed and pushed; they travel through git to another machine, another
  server, or another person.
- **A worktree is machine-local state.** It exists only in the clone where
  `git worktree add` ran.

When the operator's workflow is "decompose here, push, implement elsewhere"
— which is the normal case for this repo — the worktree that `/sdd-task`
creates is garbage *by construction*: the machine that planned the feature
is not the machine that implements it. Every `/sdd-task` run leaves behind a
branch and a checkout that nobody will ever enter.

The evidence is measurable in this clone today: 13 live worktrees under
`.claude/worktrees/`, 97 `feat-*` branches, and duplicated worktrees for the
same feature — `feat-538-workingmemory-toolkit` **and**
`feat-FEAT-538-workingmemory-toolkit` — because two different creators use
two different naming templates. `feat-FEAT-539-contracts-card-ontology` and
`feat-FEAT-539-contracts-o365-delta` both sit at the same commit
(`d7cec5906`), untouched since creation. That the `/remove-worktree` skill
exists at all is the symptom: there is a tool whose job is to clean up what
this design produces.

The second half of the problem is that worktree creation has **five owners**
with **two naming templates**:

| Creator | Template | Base ref |
|---|---|---|
| `/sdd-task` §6 | `feat-<FEAT-ID>-<slug>` | `HEAD` (feature) / `origin/main` (hotfix) |
| `sdd-worker` §3 | `feat-<FEAT-ID>-<feature-slug>` | `HEAD` — **no hotfix branch** |
| `sdd-planner` step 4 | `feat-<id>-<slug>` | `HEAD` |
| `sdd-research` step 5 | `feat-<id>-<slug>` | `origin/dev` / `origin/main` |
| `sdd-autopilot` §6 | `feat-<FEAT-ID>-<slug>` | `HEAD` |

`<FEAT-ID>` is the literal `FEAT-<NNN>`, so template one yields
`feat-FEAT-550-…` and template two yields `feat-550-…`. Two writers, two
names, one feature — hence the duplicate 538 worktrees above. `sdd-worker`
additionally drops the FEAT-466 hotfix naming/base-ref rule entirely: it
always writes `feat-…` from `HEAD`, so a hotfix routed through the worker
silently inherits unreleased `dev` commits.

### Goals

- The feature worktree is created by whoever is about to **write code in
  it**, at the moment they are about to write — not at planning time.
- `/sdd-task` produces only versioned artifacts (spec-derived tasks + index)
  and no machine-local state.
- `/sdd-start` works from a clean clone that has only pulled the task files:
  it creates the worktree it needs, idempotently.
- One executable naming/base-ref rule, shared by every creator, replacing
  the prose repeated across five markdown files.
- The FEAT-466 hotfix rule (`hotfix-<JIRA-KEY>-<slug>` from `origin/main`,
  never `HEAD`) is enforced by that shared rule, so no creator can lose it.

### Non-Goals (explicitly out of scope)

- **No existing worktree is removed or renamed.** The 13 stale worktrees and
  the in-flight `feat-FEAT-*` branches stay exactly as they are; cleaning
  them up remains a manual `/remove-worktree` operation, which already knows
  how to refuse a worktree with a live `sdd-worker` inside.
- No change to the `feat-FEAT-<NNN>-<slug>` name itself. The duplicated
  `feat-FEAT-` prefix is confirmed as canonical (decided 2026-09-11) because
  it is what `/sdd-done` greps and merges on
  (`.claude/commands/sdd-done.md:90`, and ~15 further references), what
  `/sdd-task`, `sdd-worker`, `sdd-autopilot` and `/sdd-spec` already emit,
  and what all 13 live worktrees are named. Renaming would strand in-flight
  features for a cosmetic gain.
- No change to `SubWorktreeManager`
  (`packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py`). That
  class manages **per-worker sub-worktrees inside** an already-existing
  feature worktree — a different layer, correctly owned by the code that
  writes in them.
- No audit script for stale worktrees.

---

## 2. Architectural Design

### Overview

Split the worktree lifecycle by *who has a legitimate, co-located intention
to write code*:

1. **Planning-only commands never create a worktree.** `/sdd-task` drops its
   §6 entirely. Its output points at `/sdd-start`, which will create the
   worktree on demand.
2. **Code-writing entry points ensure the worktree.** `/sdd-start` gains the
   step it never had; `sdd-worker` §3 keeps the step it already has. Both
   converge on one shared, idempotent implementation.
3. **Co-located orchestrators keep creating it, but stop hand-rolling it.**
   `sdd-planner`, `sdd-research` and `sdd-autopilot` plan *and* dispatch in
   the same run on the same machine, so their intention is contemporaneous
   and legitimate. They keep creating the worktree — but through the shared
   rule, which removes the `feat-<id>-<slug>` drift and restores the hotfix
   base-ref rule.
4. **The rule becomes code, not prose.** A pure function in
   `scripts/sdd/sdd_meta.py` decides name and base ref; a thin CLI in
   `scripts/sdd/ensure_worktree.py` performs the idempotent git plumbing.
   Five markdown files then call one command instead of repeating five
   variants of the same bash.

Point 4 follows an existing precedent in this repo: `WORK_KIND_FLOW`
(`scripts/sdd/sdd_meta.py:34`) carries the comment *"This mapping used to
live only as prose in .claude/agents/sdd-research.md (FEAT-466)"*. The same
prose-to-code hoist is applied here to the naming rule.

**Deferred creation branches from a fresher base, not a staler one.** Today
the worktree branches from the exact commit that contains the tasks.
Deferred, it branches from the current `base_branch` — which is better,
provided the executor syncs first. `ensure_worktree.py` therefore fetches
and fast-forwards `base_branch` before creating, and verifies afterwards
that the spec and the per-spec index are visible inside the new worktree
(the check `sdd-worker` §4 and `/sdd-start` already want). An executor with
a stale `dev` and no task files fails loudly at creation time instead of
silently implementing against the wrong tree.

### Component Diagram

```
                     scripts/sdd/sdd_meta.py
                     plan_worktree(FlowMeta, slug, ...) -> WorktreePlan
                                   ▲
                                   │ (pure: name + base_ref)
                     scripts/sdd/ensure_worktree.py  (CLI, idempotent git plumbing)
                                   ▲
        ┌──────────────┬───────────┼───────────┬────────────────┐
        │              │           │           │                │
   /sdd-start     sdd-worker   sdd-planner  sdd-research   sdd-autopilot
   (§3.5 new)      (§3 rewired)  (step 4)     (step 5)        (§6)
        │              │
        └──── writes code in the worktree ────┘

   /sdd-task ── writes ONLY sdd/tasks/** + index, commits, stops.
                (no git worktree add anywhere)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts/sdd/sdd_meta.py` | extends | Adds `WorktreePlan` + `plan_worktree()` beside `FlowMeta`/`resolve_flow()` |
| `.claude/commands/sdd-task.md` | modifies | §6 deleted, §7 renumbered to §6, output rewritten |
| `.claude/commands/sdd-start.md` | modifies | §3 becomes "Ensure the Worktree" (create-or-reuse) |
| `.claude/agents/sdd-worker.md` | modifies | §3 inline bash replaced by the shared CLI |
| `.claude/agents/sdd-planner.md` | modifies | step 4 uses the shared CLI (fixes `feat-<id>` drift) |
| `.claude/agents/sdd-research.md` | modifies | step 5 uses the shared CLI (keeps hotfix path) |
| `.claude/agents/sdd-autopilot.md` | modifies | §6 uses the shared CLI |
| `CLAUDE.md` | modifies | Auto-Commit table, FEAT-466 carve-out, Typical Workflow |
| `/sdd-done` | unchanged | Its `grep "feat-<FEAT-ID>"` keeps matching — naming is unchanged |
| `SubWorktreeManager` | unchanged | Different layer (per-worker sub-worktrees) |

### Data Models

```python
# scripts/sdd/sdd_meta.py
class WorktreePlan(BaseModel):
    """Where a feature/hotfix worktree goes and what it branches from."""

    name: str       # branch name AND directory basename
    path: str       # ".claude/worktrees/<name>", repo-relative
    base_ref: str   # "origin/dev" | "origin/main" | "origin/staging"
```

### New Public Interfaces

```python
# scripts/sdd/sdd_meta.py
def plan_worktree(
    meta: FlowMeta,
    *,
    slug: str,
    feature_id: str | None = None,
    jira_key: str | None = None,
) -> WorktreePlan:
    ...
```

```bash
# scripts/sdd/ensure_worktree.py  (CLI)
python -m scripts.sdd.ensure_worktree \
    --slug <feature-slug> \
    [--feature-id FEAT-<NNN>] [--jira-key <KEY>] \
    [--spec sdd/specs/<slug>.spec.md] [--index sdd/tasks/index/<slug>.json] \
    [--no-sync] [--dry-run] [--json]
# prints the absolute worktree path on stdout; exit 0 whether created or reused
# --json prints {"name","path","base_ref","created"} instead — for the dev-loop
#        subagents that must return worktree_path in a Pydantic contract
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `plan_worktree` | yes | Signature, `WorktreePlan` fields, both name templates, base-ref rule, and every `ValueError` message are fixed below | — |
| M2: `ensure_worktree.py` CLI | yes | Flags, ordering of the six steps, stdout contract and exit codes fixed below | — |
| M3: `/sdd-start` §3 | no | Requires authoring a new section and deciding what the "not in a worktree" narrative becomes | — |
| M4: `/sdd-task` §6 removal | yes | Exact lines to delete and exact replacement output block given | — |
| M5: `sdd-worker` §3 rewire | yes | Exact replacement block given | — |
| M6: co-located orchestrators | yes | Same replacement block, three files, anchors given | — |
| M7: docs (`CLAUDE.md`) | yes | Four anchored edits, new text given | — |
| M8: tests | yes | Test names and assertions enumerated in §4 | — |

### Module 1: Worktree naming rule
- **Path**: `scripts/sdd/sdd_meta.py` (extends the existing module)
- **Responsibility**: Single source of truth for a worktree's branch name,
  directory path, and base ref, derived from the flow type. Pure — no git,
  no filesystem.
- **Depends on**: `FlowMeta` (`scripts/sdd/sdd_meta.py:41`)
- **Interface Skeleton**:
  ```python
  # scripts/sdd/sdd_meta.py  (modifies scripts/sdd/sdd_meta.py:159, appended after resolve_flow)

  #: Every SDD worktree lives directly under this repo-relative directory.
  WORKTREE_ROOT: str = ".claude/worktrees"  # verified: CLAUDE.md:254

  class WorktreePlan(BaseModel):
      """Where a feature/hotfix worktree goes and what it branches from."""

      name: str
      path: str
      base_ref: str

  def plan_worktree(
      meta: FlowMeta,                       # verified: scripts/sdd/sdd_meta.py:41
      *,
      slug: str,
      feature_id: str | None = None,
      jira_key: str | None = None,
  ) -> WorktreePlan:
      """Resolve the canonical worktree name, path and base ref for a run.

      Naming (confirmed canonical 2026-09-11 — it is what /sdd-done greps):
        * ``meta.type == "feature"`` -> ``feat-<feature_id>-<slug>``, e.g.
          ``feat-FEAT-552-worktree-creation-ownership``. The duplicated
          ``feat-FEAT-`` prefix is intentional, not a bug.
        * ``meta.type == "hotfix"``  -> ``hotfix-<jira_key>-<slug>`` (FEAT-466:
          a hotfix reserves no FEAT-<NNN>; its identity is the Jira key).

      Base ref is always remote-qualified — ``origin/<meta.base_branch>`` —
      so a worktree can never inherit an unpushed local HEAD. For a hotfix
      this is ``origin/main`` by construction, since ``FlowMeta`` already
      refuses ``type='hotfix'`` with any other base branch
      (verified: scripts/sdd/sdd_meta.py:47).

      Args:
          meta: Resolved flow metadata.
          slug: Feature slug, kebab-case.
          feature_id: ``FEAT-<NNN>``; required when ``meta.type == "feature"``.
          jira_key: Jira issue key; required when ``meta.type == "hotfix"``.

      Returns:
          A ``WorktreePlan`` whose ``path`` is repo-relative.

      Raises:
          ValueError: When ``slug`` is empty; when a feature run has no
              ``feature_id`` or one not matching ``^FEAT-\d+$``; when a
              hotfix run has no ``jira_key``.
      """
  ```

### Module 2: Idempotent worktree provisioning CLI
- **Path**: `scripts/sdd/ensure_worktree.py` (new)
- **Responsibility**: The create-or-reuse git plumbing that today is
  duplicated as bash in five markdown files. Safe to call any number of
  times; never destructive.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # scripts/sdd/ensure_worktree.py  (new)

  class EnsureWorktreeError(RuntimeError):
      """Raised when the worktree cannot be provisioned (exit code 1)."""

  def ensure(
      plan: WorktreePlan,                  # verified: Module 1
      *,
      repo_root: Path,
      sync: bool = True,
      require_paths: Sequence[str] = (),
      dry_run: bool = False,
  ) -> Path:
      """Create the worktree if absent, reuse it if present, and verify it.

      Steps, in order:
        1. Reuse: if ``git worktree list --porcelain`` already lists a
           worktree whose path basename equals ``plan.name``, verify its
           checked-out branch is ``plan.name`` and return its path. A path
           collision with a DIFFERENT branch is an error, never a silent
           reuse.
        2. Sync (skipped when ``sync`` is False): ``git fetch origin
           <base_branch>``. The base ref stays remote-qualified, so no
           local branch is checked out and no local commit is touched.
        3. Refuse to create when a branch named ``plan.name`` already
           exists but is not checked out anywhere — the operator must
           decide (reuse via ``git worktree add <path> <branch>`` or pick a
           new slug). Report it, do not guess.
        4. Create: ``git worktree add -b <plan.name> <plan.path> <plan.base_ref>``.
        5. Verify: every entry of ``require_paths`` must exist inside the
           new worktree (the spec and the per-spec index). A missing entry
           means the executor branched from a base that does not carry the
           task artifacts yet — raise rather than let implementation start.
        6. Return the absolute path.

      Args:
          plan: The naming/base-ref decision from ``plan_worktree``.
          repo_root: Absolute path to the main clone.
          sync: Fetch ``origin/<base_branch>`` before creating.
          require_paths: Repo-relative paths that must exist in the worktree.
          dry_run: Resolve and report without running any mutating git command.

      Returns:
          Absolute path to the ready worktree.

      Raises:
          EnsureWorktreeError: On any of the refusal conditions above, or
              when a git command exits non-zero.
      """

  def main(argv: Sequence[str] | None = None) -> int:
      """CLI entry point. Prints the worktree path to stdout; 0 on success.

      With ``--json``, prints a single object instead —
      ``{"name": …, "path": …, "base_ref": …, "created": bool}`` — so
      ``sdd-planner``/``sdd-research`` can lift ``worktree_path`` straight into
      their ``PlannerOutput``/``ResearchOutput`` contracts without parsing prose
      (resolved in §8, 2026-09-11). Human output stays the bare path.
      """
  ```

### Module 3: `/sdd-start` ensures its own worktree
- **Path**: `.claude/commands/sdd-start.md`
- **Responsibility**: Turn §3 from passive detection into active
  provisioning — the change that makes deferred creation actually work for
  the manual lane.
- **Depends on**: Module 2
- **Interface Skeleton** *(markdown contract, not code)*:
  ```markdown
  ### 3. Ensure the Worktree      <!-- replaces "3. Detect Context", sdd-start.md:50 -->

  Resolve TYPE / BASE_BRANCH / FEAT-ID / slug from the per-spec index header
  (it carries `type` and `base_branch` — verified: sdd/tasks/index/token-budget-bedrock.json),
  then provision:

      WT=$(python -m scripts.sdd.ensure_worktree \
             --slug "<feature-slug>" --feature-id "<FEAT-ID>" \
             --spec "<spec-path>" --index "sdd/tasks/index/<feature-slug>.json")
      cd "$WT"

  Already inside a worktree whose branch matches: the command is a no-op and
  prints that path — stay where you are. If it exits non-zero, STOP and show
  its message; do NOT fall back to implementing on `base_branch`.
  ```

### Module 4: `/sdd-task` stops creating worktrees
- **Path**: `.claude/commands/sdd-task.md`
- **Responsibility**: Remove the eager creation; renumber; point the
  operator at `/sdd-start`.
- **Depends on**: Module 3 (its output must name the replacement step)
- **Interface Skeleton** *(markdown contract)*:
  ```markdown
  <!-- DELETE lines 313-329: the whole "### 6. Create the Worktree" section -->
  <!-- RENUMBER "### 7. Output" (line 330) -> "### 6. Output"           -->
  <!-- In the output block, REPLACE the "Worktree created:" stanza with: -->

  Worktree: not created — /sdd-task only produces versioned artifacts.
            /sdd-start (or sdd-worker) creates it on the machine that
            implements the feature.

  Next:
    /sdd-start <task-id>        # creates the worktree, then begins
  ```

### Module 5: `sdd-worker` uses the shared rule
- **Path**: `.claude/agents/sdd-worker.md`
- **Responsibility**: Replace the hand-rolled create-or-reuse at §3
  (lines 183-199) with the shared CLI, which also gives the worker the
  hotfix naming/base-ref rule it currently lacks.
- **Depends on**: Module 2
- **Interface Skeleton** *(markdown contract)*:
  ```markdown
  ### 3. Ensure the Worktree

      WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \
        --slug "<feature-slug>" --feature-id "<FEAT-ID>" \
        --spec "<spec-path>" --index "sdd/tasks/index/<feature-slug>.json")
      cd "$WORKTREE_PATH"

  This replaces the previous `git worktree list | grep … || git worktree add
  … HEAD` idiom. §4 "Verify SDD Files Are Visible" (line 200) is now
  enforced by `--spec`/`--index`; keep the section as a human-readable
  restatement only.
  ```

### Module 6: Co-located orchestrators
- **Path**: `.claude/agents/sdd-planner.md`, `.claude/agents/sdd-research.md`,
  `.claude/agents/sdd-autopilot.md`
- **Responsibility**: Keep creating the worktree (planning and dispatch are
  contemporaneous and on one machine) but through the shared rule, ending
  the `feat-<id>-<slug>` vs `feat-<FEAT-ID>-<slug>` drift.
- **Depends on**: Module 2
- **Interface Skeleton** *(markdown contract)*:
  ```markdown
  <!-- sdd-planner.md:54-58 and its cardinal rule at :68           -->
  <!-- sdd-research.md:95-99 and its cardinal rule at :110         -->
  <!-- sdd-autopilot.md:251-254                                    -->
  Replace each inline `git worktree add …` with:

      python -m scripts.sdd.ensure_worktree --slug <slug> \
        {--feature-id FEAT-<NNN> | --jira-key <KEY>}

  and restate the cardinal rule as: "The worktree name is whatever
  `scripts.sdd.sdd_meta.plan_worktree` returns — never hand-built."
  ```

### Module 7: Documentation
- **Path**: `CLAUDE.md`
- **Responsibility**: Make the written policy match the implemented one.
- **Depends on**: Modules 3-6
- **Interface Skeleton** *(anchored edits)*:
  ```markdown
  CLAUDE.md:243  — drop "(which `/sdd-task` and `sdd-worker` ensure HEAD is
                    on before creating the worktree)"; state that worktrees
                    branch from `origin/<base_branch>` and are created by
                    the code-writing entry point.
  CLAUDE.md:270  — the FEAT-466 example uses `feat-<id>-<slug>`; correct it
                    to `feat-FEAT-<NNN>-<slug>`.
  CLAUDE.md:321  — the `/sdd-task` row of the SDD Auto-Commit Rule table:
                    note it creates NO worktree.
  CLAUDE.md:366+ — "Typical Workflow": step 3's manual `git worktree add`
                    becomes `/sdd-start <TASK-ID>`.
  ```

### Module 8: Tests
- **Path**: `tests/sdd_scripts/test_worktree_plan.py`,
  `tests/sdd_scripts/test_ensure_worktree.py` (new)
- **Responsibility**: Lock the naming rule and the idempotency guarantee.
- **Depends on**: Modules 1, 2
- **Interface Skeleton**: see §4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_plan_feature_name_keeps_feat_prefix` | M1 | `feature` + `FEAT-552` + slug → `feat-FEAT-552-worktree-creation-ownership`, path under `.claude/worktrees/` |
| `test_plan_feature_base_ref_is_remote_qualified` | M1 | `base_branch="dev"` → `base_ref == "origin/dev"`; `"staging"` → `"origin/staging"` |
| `test_plan_hotfix_uses_jira_key_and_origin_main` | M1 | `hotfix` + `NAV-8036` → `hotfix-NAV-8036-<slug>`, `base_ref == "origin/main"` |
| `test_plan_feature_without_feature_id_raises` | M1 | `ValueError` naming the missing `--feature-id` |
| `test_plan_feature_with_bare_number_raises` | M1 | `feature_id="552"` rejected — must match `^FEAT-\d+$` |
| `test_plan_hotfix_without_jira_key_raises` | M1 | `ValueError` naming the missing `--jira-key` |
| `test_plan_empty_slug_raises` | M1 | `ValueError` |
| `test_ensure_creates_worktree_when_absent` | M2 | In a tmp git repo: creates branch + directory, returns its path |
| `test_ensure_is_idempotent` | M2 | Second call returns the same path, exit 0, `git branch --list` still shows exactly one matching branch |
| `test_ensure_rejects_path_with_foreign_branch` | M2 | Existing worktree at the path on a different branch → `EnsureWorktreeError`, nothing mutated |
| `test_ensure_rejects_existing_unchecked_branch` | M2 | Branch exists but no worktree → refuses with an actionable message |
| `test_ensure_requires_paths_visible` | M2 | `require_paths` naming a file absent from the base commit → raises, and the created worktree is not left behind |
| `test_ensure_dry_run_mutates_nothing` | M2 | `--dry-run` prints the plan; `git worktree list` unchanged |
| `test_ensure_json_output_shape` | M2 | `--json` emits one parseable object with `name`/`path`/`base_ref`/`created`; `created` is `True` on first call and `False` on the second |
| `test_sdd_task_has_no_worktree_add` | M4 | `grep -c "git worktree add" .claude/commands/sdd-task.md == 0` |
| `test_no_legacy_naming_template_remains` | M6 | No `feat-<id>-<slug>` in `.claude/**` (excluding `.claude/worktrees/`) |
| `test_every_creator_calls_ensure_worktree` | M5/M6 | Each of sdd-worker, sdd-planner, sdd-research, sdd-autopilot, sdd-start mentions `scripts.sdd.ensure_worktree` |

### Integration Tests

| Test | Description |
|---|---|
| `test_plan_then_ensure_roundtrip` | `resolve_flow()` → `plan_worktree()` → `ensure()` in a tmp repo produces a worktree whose branch equals `plan.name` and whose `git rev-parse HEAD` equals `origin/<base_branch>` |
| `test_deferred_creation_from_fresh_clone` | Clone the tmp repo into a second directory (simulating "another server"), commit task files on the origin, then run `ensure` there: worktree is created and `require_paths` are visible |

### Test Data / Fixtures

```python
@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A repo with an `origin` remote, a `dev` branch, and one commit
    containing sdd/specs/<slug>.spec.md + sdd/tasks/index/<slug>.json."""
```

---

## 5. Acceptance Criteria

- [ ] `grep -c "git worktree add" .claude/commands/sdd-task.md` returns `0`
- [ ] `.claude/commands/sdd-task.md` has sections 1-6 with no gap and no duplicate numbering
- [ ] `.claude/commands/sdd-start.md` contains a section that invokes `scripts.sdd.ensure_worktree` before any implementation step
- [ ] `grep -rn "feat-<id>-<slug>" .claude/ --exclude-dir=worktrees` returns nothing
- [ ] Each of `sdd-worker.md`, `sdd-planner.md`, `sdd-research.md`, `sdd-autopilot.md`, `sdd-start.md` references `scripts.sdd.ensure_worktree`, and none of them contains a bare `git worktree add`
- [ ] `python -m scripts.sdd.ensure_worktree --help` exits 0
- [ ] Running `ensure_worktree` twice for the same feature exits 0 both times, prints the same path, and leaves exactly one branch
- [ ] `--json` emits a single parseable object with `name`, `path`, `base_ref`, `created`; without it stdout is the bare path and nothing else
- [ ] `plan_worktree` refuses a `hotfix` without `--jira-key` and a `feature` without a well-formed `FEAT-<NNN>`
- [ ] All new tests pass: `pytest tests/sdd_scripts/ -v`
- [ ] `ruff check scripts/sdd/sdd_meta.py scripts/sdd/ensure_worktree.py` and `mypy` on both are clean
- [ ] `CLAUDE.md` no longer claims `/sdd-task` creates the worktree (lines 243, 321, Typical Workflow)
- [ ] No existing worktree under `.claude/worktrees/` is removed or renamed by any task in this feature
- [ ] `/sdd-done` is unmodified and its `grep "feat-<FEAT-ID>"` still resolves a worktree created by the new path

---

## 6. Codebase Contract

### Verified Imports

```python
from scripts.sdd.sdd_meta import FlowMeta, resolve_flow, parse, emit  # verified: scripts/sdd/sdd_meta.py:41,104,54,87
from scripts.sdd.sdd_meta import KNOWN_BRANCHES, WORK_KIND_FLOW       # verified: scripts/sdd/sdd_meta.py:29,34
from pydantic import BaseModel, model_validator                        # verified: scripts/sdd/sdd_meta.py:20
```

### Existing Class Signatures

```python
# scripts/sdd/sdd_meta.py
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})   # line 29
WORK_KIND_FLOW: dict[str, tuple[str, str]] = {...}                       # line 34

class FlowMeta(BaseModel):                                               # line 41
    type: Literal["feature", "hotfix"]                                   # line 44
    base_branch: str                                                     # line 45
    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta": ...                    # line 47-51

def parse(doc_path: Path) -> FlowMeta: ...                               # line 54
def emit(meta: FlowMeta) -> str: ...                                     # line 87
def resolve_flow(*, kind=None, doc_path=None,
                 type_override=None, base_branch_override=None
                 ) -> FlowMeta: ...                                      # line 104
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py  (NOT modified)
class SubWorktreeManager:                                                # line 76
    def __init__(self, *, base_worktree: str, feature_branch: str,
                 worktree_base_path: str) -> None: ...                   # line 78
    async def create(self, worker_id: str) -> str: ...                   # line 146
```

### Markdown anchors to modify (verified 2026-09-11)

| File | Line | Current content |
|---|---|---|
| `.claude/commands/sdd-task.md` | 313 | `### 6. Create the Worktree` |
| `.claude/commands/sdd-task.md` | 322 | `git worktree add -b feat-<FEAT-ID>-<slug> \` |
| `.claude/commands/sdd-task.md` | 326 | `git worktree add -b hotfix-<JIRA-KEY>-<slug> \` |
| `.claude/commands/sdd-task.md` | 330 | `### 7. Output` |
| `.claude/commands/sdd-task.md` | 352-357 | `Worktree created:` stanza + `cd .claude/worktrees/<worktree-name>` |
| `.claude/commands/sdd-start.md` | 50 | `### 3. Detect Context` |
| `.claude/commands/sdd-start.md` | 65 | `### 4. Mark In-Progress (in place)` |
| `.claude/agents/sdd-worker.md` | 183 | `### 3. Create the Worktree` |
| `.claude/agents/sdd-worker.md` | 190 | `WORKTREE_NAME="feat-<FEAT-ID>-<feature-slug>"` |
| `.claude/agents/sdd-worker.md` | 194-195 | `git worktree list \| grep … \|\| git worktree add … HEAD` |
| `.claude/agents/sdd-worker.md` | 200 | `### 4. Verify SDD Files Are Visible` |
| `.claude/agents/sdd-planner.md` | 54-56 | step 4, `git worktree add -b feat-<id>-<slug> … HEAD` |
| `.claude/agents/sdd-planner.md` | 68 | cardinal rule: branch name MUST match `feat-<id>-<slug>` |
| `.claude/agents/sdd-research.md` | 95-98 | step 5, hotfix + feature `git worktree add` |
| `.claude/agents/sdd-research.md` | 110 | cardinal rule: `feat-<id>-<slug>` |
| `.claude/agents/sdd-autopilot.md` | 251-254 | `#### 6. Create Worktree` |
| `CLAUDE.md` | 243 | "which `/sdd-task` and `sdd-worker` ensure HEAD is on before creating the worktree" |
| `CLAUDE.md` | 270 | `git worktree add -b feat-<id>-<slug> … origin/dev` |
| `CLAUDE.md` | 321 | `/sdd-task` row of the SDD Auto-Commit Rule table |
| `CLAUDE.md` | 366 | `## Typical Workflow` |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `plan_worktree()` | `FlowMeta` | constructor arg + `.type`/`.base_branch` | `scripts/sdd/sdd_meta.py:41` |
| `ensure_worktree.py` | `plan_worktree()` | function call | Module 1 |
| `/sdd-start` §3 | per-spec index header | `jq` on `.type` / `.base_branch` / `.feature_id` | `sdd/tasks/index/token-budget-bedrock.json` |
| `tests/sdd_scripts/` | both new modules | pytest | `tests/sdd_scripts/test_sdd_meta.py` (existing sibling) |

### Does NOT Exist (Anti-Hallucination)

- ~~`scripts/sdd/worktree.py`~~ / ~~`scripts/sdd/ensure_worktree.py`~~ — neither
  exists today; `scripts/sdd/` currently holds `calibrate_rlimit_as.py`,
  `check_id_collisions.py`, `close_task.sh`, `heal_orphans.sh`,
  `id_ledger.py`, `insight.py`, `lint_new.py`, `migrate_index.py`,
  `reserve_ids.py`, `sdd_meta.py`, `tag_yaml_fixtures.py`
- ~~`sdd_meta.worktree_name()`~~ / ~~`sdd_meta.WorktreePlan`~~ — do not exist
  yet; this feature adds them
- ~~`.worktrees/_active.json`~~ — referenced by
  `.claude/rules/worktree-start-feature.md` and `worktree-status.md`, but
  **no SDD command reads or writes it** and there is no `.worktrees/`
  directory in this repo. SDD worktrees live under `.claude/worktrees/`. Do
  not wire the new CLI to it.
- ~~`SubWorktreeManager` creates the feature worktree~~ — it does not; it
  creates **per-worker sub-worktrees** under an existing feature worktree
  (`worktree_manager.py:78`, arg `base_worktree` = "the feature's primary
  worktree"). Out of scope.
- ~~a pytest suite over `.claude/**` markdown~~ — none exists; the grep-shaped
  criteria in §5 are new tests this feature adds under `tests/sdd_scripts/`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `scripts/sdd/sdd_meta.py` is the established home for "SDD rules hoisted
  out of markdown prose" — `WORK_KIND_FLOW` carries that history in a
  comment (line 31-33). Follow it: pure logic there, git plumbing in the CLI.
- Pydantic model for `WorktreePlan`; Google-style docstrings; strict type
  hints (the module already uses `from __future__ import annotations`).
- The CLI is a plain synchronous script (like `reserve_ids.py`), not async —
  it shells out to git and is invoked from bash by agents.
- Never `git worktree remove` or `git branch -D` from this feature's code.
  Provisioning only.

### Known Risks / Gotchas

- **Executor with a stale base.** Deferred creation branches from
  `origin/<base_branch>`, so an un-fetched clone could miss the task files.
  Mitigated by step 2 (fetch) and step 5 (`require_paths` verification) of
  `ensure()`, which fails loudly rather than starting work on an empty tree.
- **`--ff-only` is deliberately not used.** `ensure()` fetches but never
  checks out or fast-forwards a local branch — the worktree branches from
  the remote ref directly. That is what makes it safe to run from inside
  another worktree, and it avoids the "reset --hard ate my commits" class of
  failure this repo has hit before.
- **A branch may already exist without a worktree** (e.g. a previous
  `/sdd-task` run before this feature landed, or a `git worktree remove`
  without `git branch -d`). `ensure()` refuses and reports rather than
  guessing — 97 `feat-*` branches exist in this clone, so this path will be
  hit in practice.
- **`sdd-worker` gains hotfix naming it never had.** Its §3 always wrote
  `feat-…` from `HEAD`. Routing it through `plan_worktree` changes behaviour
  for hotfix runs — that is the intended fix (FEAT-466), but it means a
  hotfix worker will now look for `hotfix-<KEY>-<slug>`.
- **`/sdd-done` is untouched by design.** Its `grep "feat-<FEAT-ID>"` keeps
  working only because the naming stays `feat-FEAT-<NNN>-<slug>`. Any future
  attempt to clean up the doubled prefix must update `/sdd-done` in the same
  change.
- **Running from inside a worktree.** `/sdd-start` is frequently invoked
  already inside the target worktree. Step 1 of `ensure()` must treat that
  as reuse (no-op), not as a collision.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | already required | `WorktreePlan` model — same dependency `FlowMeta` uses |
| `pyyaml` | already required | transitively, via `sdd_meta` |

No new dependency is introduced.

---

## 8. Open Questions

- [x] Which naming template becomes canonical? — *Resolved 2026-09-11 by the
  author*: `feat-FEAT-<NNN>-<slug>`. It is what `/sdd-done` greps and merges
  on, what four of the five creators already emit, and what all 13 live
  worktrees are named; the alternative would strand in-flight branches for a
  cosmetic gain. Reflected in §1 Non-Goals, M1's docstring and §5.
- [x] Do the 13 existing stale worktrees fall in scope? — *Resolved
  2026-09-11 by the author*: no. This feature fixes the cause; cleanup of
  the backlog stays a manual `/remove-worktree` operation. Reflected in §1
  Non-Goals and the last §5 criterion.
- [x] Should `sdd-planner` / `sdd-research` / `sdd-autopilot` stop creating
  worktrees too? — *Resolved during the design discussion*: no. They plan
  and dispatch in the same run on the same machine, so their intention is
  contemporaneous. They keep creating, via the shared rule (Module 6).
- [x] Should `ensure_worktree.py` also emit machine-readable output (JSON)
  for the dev-loop subagents that must return `worktree_path` in a Pydantic
  contract (`PlannerOutput`, `ResearchOutput`)? A `--json` flag is trivial to
  add now and awkward to retrofit. — *Owner: Jesus Lara*: yes

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `n/a` · Status: skipped (no exploration
> document — this spec was authored directly from a design discussion with the
> author, so §3b's precondition "an accepted brainstorm/proposal exists" is
> not met) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

**Default isolation unit**: `per-spec` — all tasks run sequentially in one
worktree, `feat-FEAT-552-worktree-creation-ownership`.

**Parallelizable tasks**: M4 (`/sdd-task` §6 removal) and M7 (`CLAUDE.md`)
touch no shared file with M1/M2 and can run in parallel with them. M3, M5 and
M6 all depend on M2's CLI contract existing, and M8 depends on M1+M2.
Everything else is sequential.

**Cross-feature dependencies**: none. FEAT-550 (`token-budget-bedrock`) and
FEAT-551 are in flight on `dev` and touch no file listed in §6.

**Self-reference (read this before starting)**: this feature edits the very
commands that drive SDD.

- The `/sdd-task` run that decomposes *this* spec still creates a worktree —
  that is the old behaviour, and it is expected. It is also the last time it
  should happen.
- Claude Code resolves `.claude/commands/` and `.claude/agents/` relative to
  the working directory, so once M3-M6 are committed in the worktree, the
  session running inside that worktree is reading the *edited* files. Land
  M1 and M2 first so that, by the time the markdown starts pointing at
  `scripts.sdd.ensure_worktree`, the script it names actually exists.
- The final verification for this feature is behavioural, not just textual:
  from the main repo, delete nothing, run `/sdd-start` for a task of a
  *different* pending feature that has no worktree, and confirm a worktree
  appears with the canonical name.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-11 | Jesus Lara | Initial draft — worktree creation moved from planning time to implementation time |
