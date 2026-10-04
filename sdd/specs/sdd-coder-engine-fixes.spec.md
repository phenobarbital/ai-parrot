---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, execution-pool, review-checkpoint, ledger-fix]
---

# Feature Specification: sdd-coder engine fixes (settlement outstanding jobs + retry-ladder hygiene)

**Feature ID**: FEAT-594
**Date**: 2026-09-23
**Author**: Jesus Lara (with Claude, via `/sdd-fix`)
**Status**: approved
**Target version**: next patch
**Source**: ledger fix group `fixgroup:526e5d08b1ca` (`wikitoolkit ledger plan-fix`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`SddCoderEngine.run_chunk` records every dispatched MCP job in
`self._job_worktrees[job_id] = worktree` and nothing ever removes it (it is
also what `wait()` uses to re-journal a job). Two readers treat that map as
"outstanding work" with **no check of the job's actual state**:

1. `end_execution` — after the busy gates pass, the snapshot-enrichment loop
   appends *every* job id ever dispatched for the worktree to
   `ExecutionSnapshot.outstanding_job_ids`, and that snapshot is durably
   published to the evidence store as the execution's settlement artifact.
2. `status()` — the degraded-persistence retry path does the same when it
   re-writes a snapshot.

`prepare_review_checkpoint` (correctly) refuses any settlement that lists
outstanding jobs, so **any execution that delivered a task through
`coder_run_chunk` can never reach a review checkpoint**, even after the job
is `done` and merged. Tests in `test_optimization_workflow_contracts.py`
work around it with `engine._job_worktrees.pop(job_id, None)`.

At the same time the pre-close busy gate reads `pool.snapshot().
outstanding_job_ids`, which the pool never populates, so a job that is
genuinely still `running` does **not** block `end_execution`.

The same fix group carries four small hygiene items in the same file.

Ledger issues covered:

| Issue | Severity | Summary |
|---|---|---|
| `issue:93abecaf1152` | critical | `end_execution` outstanding_job_ids never filters by completion state |
| `issue:00e1ae81e08d` | major | `_job_worktrees` never cleared → MCP deliveries never reach a checkpoint |
| `issue:cc372f700a47` | major | checkpoint prepare blocked by stale outstanding_job_ids after a clean close |
| `issue:466c3bcd0c9a` | minor | native retry handoff has no busy-wait (undocumented) |
| `issue:8cfe91c4adf5` | minor | vacuous-truth `all()` in the MCP-only retry-ladder diagnostic |
| `issue:0e6daa941b57` | low | native-retry helper lacks Google-style Args/Returns |
| `issue:fffc637dfc99` | low | `plan()`'s `complexity_plan_stale` except-branch is unreachable |

### Goals
- "Outstanding job" means **a JobTable job in state `running`** that belongs
  to the execution — one definition, used by the busy gate, the close
  snapshot and the `status()` persistence retry.
- A `running` MCP job blocks `end_execution` with `execution_busy`.
- A settled (`done`/`error`) job never appears in a published settlement, so
  `prepare_review_checkpoint` accepts an execution that delivered via
  `run_chunk`.
- Remove the test-side `_job_worktrees.pop` workarounds.
- Land the four hygiene items without behavior change.

### Non-Goals (explicitly out of scope)
- Relaxing `prepare_review_checkpoint`'s gate — an outstanding job in a
  closed settlement remains a hard refusal (the fix is at the producer).
- Pruning `_job_worktrees` — `wait()` still needs it to re-journal.
- Repairing settlement artifacts already published with stale job ids
  (re-closing a new execution publishes a fresh one).
- Adding a busy-wait to the native retry selector.

---

## 2. Architectural Design

### Overview

Add one private helper on `SddCoderEngine`:

```python
def _outstanding_job_ids(self, execution_id: str, worktree: str) -> List[str]:
    """Job ids of this execution whose JobTable state is still 'running'."""
```

Scope rule: a job belongs to the execution when `job.execution_id ==
execution_id`; a job with an empty `execution_id` (legacy, non-execution
dispatch) belongs to it when its `_job_worktrees` entry equals the
execution's canonical worktree. Unknown job ids (not in `JobTable`) are
skipped. Ordered deterministically (insertion order of `_job_worktrees`).

Callers:
- `end_execution` busy gate: replace the `snapshot.outstanding_job_ids`
  check (always empty) with `self._outstanding_job_ids(...)`; non-empty →
  `CoderFailure("execution_busy", …)`.
- `end_execution` enrichment: `snapshot.outstanding_job_ids` gets the
  helper's result (empty by construction once the gate passed).
- `status()` persistence retry: same helper instead of the raw map walk.

### Integration Points

| Existing Component | Change | Notes |
|---|---|---|
| `SddCoderEngine.end_execution` | modify | busy gate + enrichment use the helper |
| `SddCoderEngine.status` | modify | persistence-retry enrichment uses the helper |
| `prepare_review_checkpoint` | none | gate unchanged; now receives a clean settlement |
| `JobTable` | none | read via `self._jobs.get()` |

### Data Models
No new models. `ExecutionSnapshot.outstanding_job_ids` keeps its type and meaning
("still-running jobs"), now actually honored.

---

## 3. Module Breakdown

### Module 1: outstanding-job definition (`engine.py`)
Helper + three call sites above. Covers `93abecaf1152`, `00e1ae81e08d`, `cc372f700a47`.

### Module 2: retry-ladder hygiene (`engine.py`)
- `_select_native_retry_seat`: Google-style docstring with Args/Returns and a
  paragraph explaining why it never waits on a busy native seat (a native
  seat is released only by the orchestrator's `merge()`, which may be
  sequenced after this job's `coder_wait`, so waiting inside the job could
  park it until the wait timeout; a busy native seat is treated as
  unavailable and the caller emits the explicit `complex_model_unavailable`
  block). Covers `466c3bcd0c9a`, `0e6daa941b57`.
- `_run_task` MCP-only diagnostic: materialize the candidate seats in
  `remaining` and require the list to be non-empty before `all(kind ==
  "native")`. Covers `8cfe91c4adf5`.
- `plan()`: drop the unreachable `if exc.code == "complexity_plan_stale": raise`
  branch (`_compute_assessment` only raises `complexity_contract_invalid` /
  `complexity_audit_failed`); keep the comment accurate. Covers `fffc637dfc99`.

### Module 3: tests
Remove both `_job_worktrees.pop` workarounds in
`test_optimization_workflow_contracts.py` and add regression tests.

---

## 4. Test Specification

### Unit / integration tests (`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/`)
| Test | Description |
|---|---|
| `test_end_execution_settlement_excludes_finished_jobs` | run_chunk → wait (done) → end_execution: published/persisted snapshot has `outstanding_job_ids == []` |
| `test_end_execution_busy_while_job_running` | a job whose runner is blocked → `end_execution` raises `execution_busy`; after release it closes |
| `test_outstanding_job_ids_scoped_to_execution` | a running job from another execution / worktree is not counted |
| existing workflow-contract tests | pass with the `pop` workarounds removed |

---

## 5. Acceptance Criteria
- [ ] AC1: After a `run_chunk` job reaches `done`, `end_execution` publishes a settlement with empty `outstanding_job_ids`, and `prepare_review_checkpoint` succeeds for it.
- [ ] AC2: `end_execution` raises `execution_busy` while an execution-scoped job is `running`.
- [ ] AC3: `status()`'s persistence retry never re-adds finished jobs.
- [ ] AC4: No `_job_worktrees.pop` workaround remains in tests.
- [ ] AC5: The four hygiene items land with no behavior change beyond AC1–AC3.
- [ ] AC6: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` passes; `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.checkpoint import prepare_review_checkpoint
```

### Existing Class Signatures
- `JobTable.get(job_id) -> CoderJob` — raises `KeyError` when unknown (`jobs.py:89`).
- `CoderJob.state: Literal["running", "done", "error"]`, `CoderJob.execution_id: str` (`models.py`).
- `SddCoderEngine._job_worktrees: Dict[str, str]` (`engine.py:383`), filled at `run_chunk` (`engine.py:3588`), read by `wait()` (`engine.py:3624`).

### Edit Sites (Blueprint Anchors)
- `engine.py:787` `end_execution` — busy gate `if snapshot.outstanding_job_ids:` (~839) and enrichment loop (~859-862).
- `engine.py:~2640` `status()` — `for job_id_iter, job_wt in list(self._job_worktrees.items()):`.
- `engine.py:~1509` `plan()` — `if exc.code == "complexity_plan_stale": raise`.
- `engine.py:3158` `_select_native_retry_seat` docstring.
- `engine.py:~3393` `_run_task` — `and all(candidate.kind == "native" for candidate in pool._seats if candidate.label in remaining)`.
- `tests/.../test_optimization_workflow_contracts.py:~284-296`, `~629-633` — workaround blocks.

### Does NOT Exist (Anti-Hallucination)
- No public API to reap `_job_worktrees`; no `JobTable.remove`.
- `ExecutionPool` does not track MCP jobs — `pool.snapshot().outstanding_job_ids` is always empty.

---

## 7. Implementation Notes & Constraints
- Keep `_job_worktrees` intact (needed by `wait()`).
- `JobTable.get` deep-copies; reading `self._jobs._jobs` is acceptable only via the public `get()`.
- Hard cut is fine (no external consumers).

## 8. Open Questions
None.

## 9. Design Research Cross-Check
Status: skipped (ledger-driven fix lane; scope fully determined by the filed issues)

## Revision History
| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-09-23 | Authored by `/sdd-fix` from fixgroup:526e5d08b1ca |
