# TASK-3670: Outstanding MCP jobs = still-running jobs (end_execution / status / settlement)

**Feature**: FEAT-594 — sdd-coder engine fixes (settlement outstanding jobs + retry-ladder hygiene)
**Spec**: `sdd/specs/sdd-coder-engine-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:93abecaf1152, issue:00e1ae81e08d, issue:cc372f700a47

---

## Context

Spec §1/§2 Module 1 + Module 3. `run_chunk` records every job in
`SddCoderEngine._job_worktrees` and nothing removes it (`wait()` needs it to
re-journal). `end_execution`'s enrichment loop (engine.py:860) and `status()`'s
persistence-retry loop (engine.py:2640) copy **every** entry for the worktree
into `ExecutionSnapshot.outstanding_job_ids` without looking at the job's
state, so the durably published settlement always lists finished jobs and
`prepare_review_checkpoint` (checkpoint.py:484) refuses it forever. Meanwhile
the pre-close busy gate (engine.py:839) reads `pool.snapshot().
outstanding_job_ids`, which the pool never fills, so a genuinely running job
does not block close.

Ledger issues: `issue:93abecaf1152` (critical), `issue:00e1ae81e08d` (major),
`issue:cc372f700a47` (major — symptom at the checkpoint; fixed at the producer,
checkpoint.py is intentionally unchanged per spec Non-Goals).

## Scope

- Add `SddCoderEngine._outstanding_job_ids(execution_id, worktree) -> List[str]`.
- Use it in the `end_execution` busy gate, the `end_execution` enrichment and
  the `status()` persistence retry.
- Remove both `engine._job_worktrees.pop(job_id, None)` workarounds (and their
  "CONFIRMED DEFECT" comment blocks) from `test_optimization_workflow_contracts.py`.
- Add `test_outstanding_jobs.py` regression tests.

**NOT in scope**: pruning `_job_worktrees`; any change to `checkpoint.py`;
the hygiene items (TASK-3671).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | helper + 3 call sites |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py` | MODIFY | drop the two `_job_worktrees.pop` workarounds |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_outstanding_jobs.py` | CREATE | regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_optimization_workflow_contracts.py:32
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable  # verified: engine.py:59
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: test_optimization_workflow_contracts.py:34
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py
class JobTable:
    def create(self, feature_id: str, task_ids: List[str], runner, *, execution_id: str) -> CoderJob  # :25
    def get(self, job_id: str) -> CoderJob  # :89 — raises KeyError when unknown; returns a deep copy
    async def wait(self, job_id: str, timeout_s: float) -> CoderJob  # :96

# models.py — CoderJob
state: Literal["running", "done", "error"]
execution_id: str   # "" for legacy non-execution dispatches

# engine.py
self._jobs  # JobTable instance
self._job_worktrees: Dict[str, str] = {}  # :383 job_id -> feature worktree (filled in run_chunk :3588, read by wait :3624)
async def end_execution(self, execution_id: str) -> "ExecutionPoolView"  # :787
async def status(self, job_id: str) -> CoderJob  # :2612
pool.worktree_path  # canonical worktree of an ExecutionPool
```

### Does NOT Exist
- ~~`JobTable.remove` / `JobTable.running_jobs`~~ — only `running_task_ids(execution_id)` exists (returns task ids, not job ids).
- ~~`ExecutionPool` tracking MCP jobs~~ — `pool.snapshot().outstanding_job_ids` is always empty.
- ~~a public API that reaps `_job_worktrees`~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_outstanding_jobs.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.status",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/jobs.py#JobTable"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper directly above `async def end_execution` — *why*: one definition of "outstanding" shared by all three readers (spec §2).
2. Replace the busy-gate check at engine.py:839 — *why*: the pool snapshot never carries jobs, so a running job must be detected from `JobTable`.
3. Replace both enrichment loops (engine.py:860, :2640) — *why*: finished jobs must never reach a published settlement (AC1, AC3).
4. Delete the two workaround blocks in the workflow-contract test — *why*: AC4; the existing mixed-delivery test then proves AC1 end-to-end.
5. Write `test_outstanding_jobs.py` — *why*: AC2 + scoping rule.

### `engine.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -c '    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":' engine.py)
# BEFORE — insert above `    async def end_execution(self, execution_id: str) -> "ExecutionPoolView":` (verified: engine.py:787)
    def _outstanding_job_ids(self, execution_id: str, worktree: str) -> List[str]:
        """Return the job ids of *execution_id* whose JobTable state is still ``running``.

        A job belongs to the execution when its ``execution_id`` matches; a
        legacy job with an empty ``execution_id`` belongs to it when its
        ``_job_worktrees`` entry is the execution's canonical *worktree*.
        ``_job_worktrees`` is never pruned (``wait()`` re-journals from it),
        so a job's presence there is NOT evidence it is outstanding -- only
        its live state is.

        Args:
            execution_id: The execution being closed or persisted.
            worktree: The execution's canonical worktree path.

        Returns:
            Job ids in dispatch order; empty when every job has settled.
        """
        outstanding: List[str] = []
        for job_id, job_wt in list(self._job_worktrees.items()):
            try:
                job = self._jobs.get(job_id)
            except KeyError:
                continue
            # FILL IN: skip unless job.state == "running" and
            #   (job.execution_id == execution_id or (not job.execution_id and job_wt == worktree))
            #   — bounded by spec §2 scope rule
            outstanding.append(job_id)
        return outstanding
```
**Why**: `JobTable.get` is the public read (deep copy); unknown ids are skipped rather than raising because a job id is only ever added by `run_chunk` after `create`.

### `engine.py` (MODIFY) — busy gate
```python
# occurrences: 1 (verified: grep -c 'if snapshot.outstanding_job_ids:' engine.py)
# REPLACE the block starting at `            # Check outstanding jobs` / `if snapshot.outstanding_job_ids:` (verified: engine.py:838-843)
            # Check outstanding jobs -- from the JobTable, since the pool never tracks MCP jobs
            running_jobs = self._outstanding_job_ids(execution_id, pool.worktree_path)
            if running_jobs:
                raise CoderFailure(
                    "execution_busy",
                    f"execution {execution_id} has {len(running_jobs)} outstanding jobs",
                )
```

### `engine.py` (MODIFY) — end_execution enrichment
```python
# occurrences: 1 (verified: grep -c 'for job_id, job_wt in list(self._job_worktrees.items()):' engine.py)
# REPLACE engine.py:859-862 (comment + 3-line loop)
        # Outstanding = still-running jobs only (empty once the busy gate above passed)
        for job_id in self._outstanding_job_ids(execution_id, canonical_worktree):
            if job_id not in snapshot.outstanding_job_ids:
                snapshot.outstanding_job_ids.append(job_id)
```

### `engine.py` (MODIFY) — status() persistence retry
```python
# occurrences: 1 (verified: grep -c 'for job_id_iter, job_wt in list(self._job_worktrees.items()):' engine.py)
# REPLACE engine.py:2640-2642
                for job_id_iter in self._outstanding_job_ids(execution_id, pool.worktree_path):
                    if job_id_iter not in snapshot.outstanding_job_ids:
                        snapshot.outstanding_job_ids.append(job_id_iter)
```

### `test_optimization_workflow_contracts.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'engine._job_worktrees.pop(job_id, None)' test_optimization_workflow_contracts.py)
# FILL IN: disambiguate — delete the "CONFIRMED DEFECT" comment block + pop line in
#   test_mixed_delivery_checkpoint_fresh_review (~:284-296) and in test_stale_fix_and_full_compatibility (~:626-633)
```

### `test_outstanding_jobs.py` (CREATE)
```python
"""FEAT-594: outstanding MCP jobs are the still-running ones (issue:93abecaf1152)."""

from __future__ import annotations

import asyncio

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine


def _bare_engine() -> SddCoderEngine:
    # FILL IN: build an engine without probing/dispatch (object.__new__ + the
    #   attributes _outstanding_job_ids reads: _jobs = JobTable(), _job_worktrees = {})
    ...


@pytest.mark.asyncio
async def test_finished_jobs_are_not_outstanding() -> None:
    """A done job is not outstanding; a running one is."""
    # FILL IN


@pytest.mark.asyncio
async def test_outstanding_scoped_to_execution() -> None:
    """Running jobs of another execution / legacy jobs of another worktree are ignored."""
    # FILL IN


@pytest.mark.asyncio
async def test_end_execution_busy_while_job_running() -> None:
    """end_execution raises execution_busy while an execution job is running (AC2)."""
    # FILL IN — may reuse fixtures from test_optimization_workflow_contracts.py / test_execution_pool_integration.py
```

### FILL IN checklist
- [ ] helper filter condition — spec §2 scope rule
- [ ] workaround removal at both sites — AC4
- [ ] three regression tests — AC2, scoping

---

## Acceptance Criteria

- [ ] AC1: `test_mixed_delivery_checkpoint_fresh_review` passes with no `_job_worktrees.pop` (checkpoint accepted after run_chunk delivery).
- [ ] AC2: `end_execution` raises `execution_busy` while an execution-scoped job is `running`.
- [ ] AC3: `status()` persistence retry never re-adds finished jobs.
- [ ] AC4: `grep -c '_job_worktrees.pop' packages/ai-parrot/tests` is 0.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_outstanding_jobs.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`

---

## Completion Note

**Completed by**: claude-opus-5-5 via /sdd-fix
**Date**: 2026-09-23
**Notes**: Added `SddCoderEngine._outstanding_job_ids()` (running JobTable jobs, scoped by execution_id, legacy fallback by worktree) and used it in the end_execution busy gate, the end_execution snapshot enrichment and status()'s persistence retry. Removed both `_job_worktrees.pop` workarounds; `test_mixed_delivery_checkpoint_fresh_review` now reaches `prepare_review_checkpoint` unaided. New `test_outstanding_jobs.py` (3 tests). Validation: 26 passed across the four listed files; ruff clean.

**Deviations from spec**: none (checkpoint.py intentionally unchanged)
