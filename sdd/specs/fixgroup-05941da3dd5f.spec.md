---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, dev-loop, sandbox, ledger-fix]
---

# Feature Specification: Retire the `dirty_task_worktree` contract

**Feature ID**: FEAT-587
**Date**: 2026-09-21
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.28.x

**Ledger issue**: `issue:88b5c7d679c1` (kind `bug`, severity **critical**, group
`fixgroup:05941da3dd5f`) — *"Engine must extract and commit the coder's work:
`_consolidate` fails a good attempt with `dirty_task_worktree` because sandboxed
seats are designed not to commit"*.
**Supersedes**: `issue:c4d0e7a028ca` (closed — misframed as a `codex` defect).
**Decision record**: `mem-c163c2dde8ff`.

---

## 1. Motivation & Business Requirements

### Problem Statement

A coder seat runs sandboxed with `.git` **read-only by design**. It delivers its
work in the attempt worktree and cannot commit it; producing the commit is the
orchestrator's job. `SddCoderEngine._consolidate` used to open with a clean-tree
precondition, so it failed exactly the attempts that behaved correctly —
`dirty_task_worktree`, work discarded — and that failure chained onward into a
`dirty_delivery` model suspension.

**The engine-side half of this is already fixed.** Commit `ed267c217`
("fix(sdd-coder): engine extracts and commits the coder's work", merged via
PR #1449 → `f4fd8cbdc`) added `_commit_declared_changes`, which stages **only**
the task markdown's declared files (`parse_task_files` — never the coder-reported
`DevelopmentOutput.files_changed`, which would let a seat widen its own scope),
never stages an `sdd/` path, commits them on the attempt branch, and reports any
undeclared leftover as a `fidelity_violation` instead of dropping it.

**What remains is the contract that fix orphaned.** The surrounding machinery
still encodes the pre-`ed267c217` behaviour, and every one of these paths is now
**unreachable** or **wrong**:

| Leftover | Location | Why it is now wrong |
|---|---|---|
| Dirty-retry branch in `_run_task` | `engine.py:3186`, `:3199-3201` | `_consolidate` can no longer return `outcome="failed"` with a `dirty_task_worktree:`-prefixed diagnostic, so the branch and the cross-seat retry it guards are dead code |
| `_run_task` docstring | `engine.py:3170` | Documents a retryable first-attempt `dirty_task_worktree` outcome that cannot occur |
| `dirty_delivery` suspension reason | `engine.py:2908-2909` | Its only producer was `engine.py:3200`; with that dead, no seat can ever be suspended for dirty delivery |
| `dirty_task_worktree` error code | `models.py:60` (member of `ERROR_CODES: frozenset[str]`, declared line 46) | Advertised in the MCP error-code enum but never emitted |
| Operator docs | `docs/dev_loop/sdd-coder-orchestrator.md:433-434` | Tells operators "nothing is merged until the branch is clean" — the opposite of current behaviour |
| FEAT-549 **AC-22** | `sdd/specs/sdd-worker-subagents.spec.md:818` | *"A task worktree with uncommitted or untracked changes is never merged (`dirty_task_worktree`)"* — now directly contradicted by the deliberate design |

Leaving this in place is not cosmetic. A reader of the spec tree, the error-code
enum or the operator docs is told the system rejects uncommitted deliveries,
while the running system extracts and merges them. The next agent to touch
`_run_task` will reason from a contract that no longer holds.

### Goals
- Make the code, the error-code enum, the operator docs and the FEAT-549
  acceptance criteria agree with the behaviour `ed267c217` actually shipped.
- Delete the unreachable retry/suspension paths rather than leave them as traps.
- Preserve read-compatibility with ledger rows already written under the old
  contract.

### Non-Goals (explicitly out of scope)
- Re-implementing or revising `_commit_declared_changes` — it landed in
  `ed267c217` and its tests pass; this feature does not touch its logic.
- Widening any coder seat's sandbox write scope. Explicitly rejected in
  `mem-c163c2dde8ff`: `.git` stays read-only to a seat.
- The `dirty_feature_worktree` code (`models.py:59`), which is a different,
  still-live precondition on the **feature** worktree.
- Any change to `check_fidelity`, the merge lock, or `_consolidate_diff_base`.

---

## 2. Architectural Design

### Overview

Three aligned removals plus two documentation corrections. No new component, no
new public interface, no behaviour change to any path that is currently
reachable — this feature's entire deliverable is that the map matches the
territory.

### Component Diagram

```
_run_attempt ──→ _consolidate ──→ _commit_declared_changes   (ed267c217: ships, keep)
                      │                    │
                      │                    ├─ clean/committed ──→ fidelity ──→ merge
                      │                    └─ undeclared left ──→ fidelity_violation
                      │
                      └──X  dirty_task_worktree                  (M1: delete — unreachable)
                                   │
                                   └──X _classify_failure_reason → "dirty_delivery"  (M1: delete)

models.SDD_CODER_ERROR_CODES ──X "dirty_task_worktree"           (M2: delete)
coder_suspensions.SuspensionReason ── "dirty_delivery"           (M2: KEEP, read-only — see §8 Q1)

docs/dev_loop/sdd-coder-orchestrator.md:433 ──→ rewrite          (M3)
sdd/specs/sdd-worker-subagents.spec.md:818 (AC-22) ──→ supersede (M3)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SddCoderEngine._run_task` | modifies | Drop the dead dirty-retry branch and correct the docstring |
| `SddCoderEngine._classify_failure_reason` | modifies | Drop the `dirty_delivery` branch |
| `sdd_coder/models.py` error-code enum | modifies | Drop `dirty_task_worktree` |
| `knowledge/wiki/ledger/coder_suspensions.py` | unchanged (see §8 Q1) | `SuspensionReason` keeps `dirty_delivery` for historical-row parsing |
| `SddCoderEngine._commit_declared_changes` | unchanged | Landed in `ed267c217`; this feature must not alter it |

### Data Models

No new models. One `Literal` member is removed from the MCP error-code enum in
`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`.

### New Public Interfaces

None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: engine dead-path removal | yes | Exact line ranges and the replacement control flow are fixed in §6 | — |
| M2: error-code enum | yes | Single `Literal` member removal, line fixed in §6 | — |
| M3: docs + AC-22 supersession | yes | Both target lines and the replacement wording are fixed below | — |

### Module 1: Engine dead-path removal
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
- **Responsibility**: Delete the two unreachable `dirty_task_worktree` paths and
  correct the docstring that advertises them.
- **Depends on**: nothing (all changes are deletions within one file)
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
  # (modifies engine.py:3155-3305 and engine.py:2908-2909)

  class SddCoderEngine:
      async def _run_task(
          self,
          ctx: _FeatureCtx,
          task: PlannedTask,
          seat: RosterSeat,
          *,
          job_id: str,
          execution_id: Optional[str] = None,
          pool: Optional["ExecutionPool"] = None,
      ) -> TaskResult:
          """Run up to two attempts, retrying DISPATCH failures on another MCP seat.

          A seat that delivers its declared files without committing them is not a
          failure: `.git` is read-only to a sandboxed seat by design and
          `_consolidate` extracts and commits the deliverable itself
          (`_commit_declared_changes`, FEAT-587 / ed267c217). Only dispatch errors
          are retried on a fresh seat; fidelity violations and merge conflicts are
          preserved for the orchestrator to handle.
          """

      def _classify_failure_reason(
          self, error: str, error_class: str, outcome: Optional[str] = None
      ) -> Optional[str]:
          """Map a failure to a suspension reason, or None when not suspendable.

          There is no `dirty_delivery` reason: an uncommitted-but-declared
          delivery is the expected shape of a sandboxed seat's work and is
          extracted by the engine, never charged against the model.
          """
  ```
  Concretely: after `result = await self._consolidate(...)` the
  `if not (result.outcome == "failed" and result.diagnostics.startswith("dirty_task_worktree:"))`
  guard collapses — the body runs unconditionally and returns `final_result`, and
  the three lines that follow it (`err = result.diagnostics`, the
  `rec.model_copy(update={"error": err, "error_class": "dirty_task_worktree"})`
  and `attempts[-1] = rec`) are deleted. The `if err:` block below is reached
  only from the dispatch-error path, as it already is in practice.

### Module 2: Error-code enum
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`
- **Responsibility**: Stop advertising an error code the server can no longer
  return.
- **Depends on**: Module 1 (remove the producer before the declaration)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:60
  # Delete the "dirty_task_worktree" member. "dirty_feature_worktree" (line 59)
  # is a different, still-live precondition and MUST stay.
  ```

### Module 3: Documentation and AC-22 supersession
- **Path**: `docs/dev_loop/sdd-coder-orchestrator.md`,
  `sdd/specs/sdd-worker-subagents.spec.md`
- **Responsibility**: Correct the operator-facing error list and mark FEAT-549's
  AC-22 superseded rather than silently false.
- **Depends on**: Modules 1–2
- **Content contract**:
  - `docs/dev_loop/sdd-coder-orchestrator.md:433-434` — replace the
    `dirty_task_worktree` bullet with a statement of the real behaviour: a seat
    delivers uncommitted work by design, the engine commits the task's declared
    files itself, and an **undeclared** leftover surfaces as `fidelity_violation`
    with `unexpected_files`.
  - `sdd/specs/sdd-worker-subagents.spec.md:818` — annotate AC-22 as
    **superseded by FEAT-587**, citing `ed267c217` and `mem-c163c2dde8ff`. Do not
    delete the line: FEAT-549 is a completed feature and its spec is a historical
    record. The S5 row at `:1170` gets the same one-line annotation.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_no_dirty_task_worktree_producer` | M1/M2 | In `test_engine_dispatch.py`. Asserts `"dirty_task_worktree"` appears nowhere in `sdd_coder/engine.py` or `sdd_coder/models.py` — the regression guard that keeps the contract from creeping back |
| `test_classify_failure_reason_ignores_uncommitted_delivery` | M1 | In `test_engine_dispatch.py`, beside the existing `_classify_failure_reason` cases (`:788-860`): returns `None` for an error that previously classified as `dirty_delivery` |

### Integration Tests

Already present and must keep passing **unchanged** — they encode the behaviour
this feature is aligning the contract to:

| Test | Description |
|---|---|
| `test_uncommitted_declared_work_is_extracted_and_merged` | `test_integration_chunk.py:164` — a seat in `"uncommitted"` mode is extracted and merged on the FIRST attempt, no retry burned |
| `test_engine_commits_uncommitted_declared_work` | `test_engine_plan_merge.py:154` — consolidation commits the declared file |
| *(undeclared-leftover case)* | `test_engine_plan_merge.py:132-149` — leftovers surface as `undeclared_files_left_uncommitted`, never dropped |

### Test Data / Fixtures

Existing fixtures only: `git_sandbox_feature`, `noop_probe`,
`three_seat_roster`, and the fake dispatcher's `"uncommitted"` mode
(`test_integration_chunk.py:45`, `:63-66`). No new fixture is required.

---

## 5. Acceptance Criteria

- [ ] **AC-1** `grep -rn "dirty_task_worktree" packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/` returns no hit outside a comment explaining the retirement.
- [ ] **AC-2** `_run_task` returns the consolidation result unconditionally when `_run_attempt` reported no dispatch error; no retry is burned for an uncommitted-but-declared delivery.
- [ ] **AC-3** `_classify_failure_reason` has no `dirty_delivery` branch, and no code path assigns `error_class="dirty_task_worktree"`.
- [ ] **AC-4** `dirty_task_worktree` is absent from the `models.py` error-code enum; `dirty_feature_worktree` is still present.
- [ ] **AC-5** `SuspensionReason` still accepts `"dirty_delivery"`, so a ledger row written before this feature still parses (see §8 Q1).
- [ ] **AC-6** `docs/dev_loop/sdd-coder-orchestrator.md` describes the extract-and-commit behaviour; no sentence claims a dirty branch blocks the merge.
- [ ] **AC-7** FEAT-549 AC-22 and its S5 row are annotated as superseded by FEAT-587, with the `ed267c217` citation.
- [ ] **AC-8** `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -v` passes, with the three integration tests in §4 unmodified.
- [ ] **AC-9** `ruff check` and `black --check` clean on every changed file.
- [ ] **AC-10** `issue:88b5c7d679c1` closed with `--resolved-by task:TASK-<NNN>`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` @ `3bcbcb034` on 2026-09-21.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine  # verified: sdd_coder/engine.py
from parrot.flows.dev_loop.sdd_coder.models import TaskResult, DevelopmentOutput  # verified: sdd_coder/models.py
from parrot.knowledge.wiki.ledger.coder_suspensions import SuspensionReason  # verified: coder_suspensions.py:45
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
class SddCoderEngine:
    async def _commit_declared_changes(          # line 2069  — DO NOT MODIFY (ed267c217)
        self, task: PlannedTask, expected: List[str], *, branch: str, path: str, feature: str
    ) -> Optional[TaskResult]: ...
    async def _consolidate(                       # lines 2148-2266
        self, ctx: _FeatureCtx, manager: SubWorktreeManager, task: PlannedTask, *, branch: str, path: str
    ) -> TaskResult: ...
    def _classify_failure_reason(               # defined line 2888
        self, error: str, error_class: str, outcome: Optional[str] = None
    ) -> Optional[str]: ...                       # "dirty_delivery" branch at lines 2908-2909
    async def _run_task(                          # lines 3155-3305
        self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *,
        job_id: str, execution_id: Optional[str] = None, pool: Optional["ExecutionPool"] = None,
    ) -> TaskResult: ...
    #   docstring naming the dead outcome ....... line 3170
    #   unreachable guard ....................... line 3186
    #   dead err/error_class assignment ......... lines 3199-3201
    #   call site of _commit_declared_changes ... line 2179
```

### Integration Points

| Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_consolidate` | `_commit_declared_changes` | direct await, result short-circuits on non-`None` | `engine.py:2179-2181` |
| `_run_task` | `_classify_and_suspend` | only under `if err:` | `engine.py:3203-3215` |
| `_classify_failure_reason` | `SuspensionReason` literal | returned string | `coder_suspensions.py:45-53` |

### Does NOT Exist (Anti-Hallucination)

- ~~`test_engine_rejects_dirty_task_worktree`~~ — **removed** by `ed267c217`; do not restore it. It exists only in the stale worktree `.claude/worktrees/feat-FEAT-564-…--pool/` and in `packages/ai-parrot/build/`, neither of which is a source of truth.
- ~~`packages/ai-parrot/build/…/sdd_coder/engine.py`~~ — a stale build artifact that still carries the pre-`ed267c217` code. **Never edit it**; it is not on `sys.path` for the tests.
- ~~`SddCoderEngine._suspension_reason`~~ — the classifier is named **`_classify_failure_reason`** (`engine.py:2888`). No `_suspension_reason` method exists.
- ~~`DevelopmentOutput.files_changed` as a staging list~~ — deliberately NOT used for staging; `parse_task_files(task_md)` is the only list that may be staged.
- ~~a `--sandbox danger-full-access` coder dispatch~~ — explicitly rejected in `mem-c163c2dde8ff`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Deletions only in M1/M2 — do not "improve" adjacent logic while you are there.
- Keep `self.logger`; no `print`.
- 120-column lines, `black` formats, `ruff check` is the gate.

### Known Risks / Gotchas
- **Stale copies mislead greps.** `packages/ai-parrot/build/lib.linux-x86_64-cpython-312/…` and `.claude/worktrees/feat-FEAT-564-…--pool/…` both still contain the old `_consolidate`. Scope every search to `packages/ai-parrot/src` and `packages/ai-parrot/tests`.
- **Historical ledger rows.** Removing `"dirty_delivery"` from `SuspensionReason` would break parsing of suspension rows written before `ed267c217`. M2 therefore stops at the `models.py` code; `coder_suspensions.py` is deliberately left alone (AC-5, §8 Q1).
- **AC-22 is in a completed spec.** Annotate, do not delete — FEAT-549's spec is a historical record.

### External Dependencies
None.

---

## 8. Open Questions

- [ ] **Q1** — Should `"dirty_delivery"` eventually be dropped from `SuspensionReason` (`coder_suspensions.py:49`) once no live ledger row carries it, or kept permanently as a read-compat member? This spec assumes **kept** (AC-5). *Owner: Jesus Lara*
- [ ] **Q2** — `issue:88b5c7d679c1` has an empty `about`/`files` list, so `/sdd-fix`'s file-diff close key cannot be satisfied automatically. Confirm closing on `--resolved-by task:TASK-<NNN>` evidence alone. *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · **Status: skipped (spec authored by `/sdd-fix` directly from ledger
> `issue:88b5c7d679c1`; there is no accepted brainstorm/proposal document for the
> `codex` seat to review, and the pass is optional and never blocking)**
> · Transcript: none.

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-21 | Jesus Lara | Initial draft — scoped to the contract left orphaned by `ed267c217` |
