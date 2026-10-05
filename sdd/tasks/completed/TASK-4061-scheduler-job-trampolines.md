# TASK-4061: Picklable scheduler job trampolines and manager registry

**Feature**: FEAT-631 — Scheduler multi-worker correctness
**Spec**: `sdd/specs/scheduler-multiworker-correctness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / Goal G4. APScheduler 3.11.2 serializes an instance-method job by pickling `func.__self__`, the whole
`AgentSchedulerManager`, which raises `TypeError: Schedulers cannot be serialized`. This task creates the module-level
coroutines that every `add_job` will point at (wired by TASK-4064 and TASK-4065), plus the process-local registry they use to
find the live manager and the `SKIPPED` sentinel that `job_success` short-circuits on (TASK-4063).

---

## Scope

- Create `parrot/scheduler/jobs.py` with: `SKIPPED`, `_MANAGERS`, `register_manager`, `unregister_manager`, `get_manager`,
  `run_db_schedule`, `run_db_schedule_now`, `run_auto_schedule`.
- The trampolines only resolve the manager and delegate. They call manager methods that **do not exist yet**
  (`_run_db_schedule`, `_run_auto_task`, `_fire_coordinator.release_running`); TASK-4064/4065 create them. Test them with a
  stub manager object.
- Write `tests/scheduler/test_jobs.py`.

**NOT in scope**: changing `manager.py` (TASK-4063/4064/4065), coordination (TASK-4062).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` | CREATE | trampolines + registry + sentinel |
| `packages/ai-parrot-server/tests/scheduler/test_jobs.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.scheduler.manager import AgentSchedulerManager   # verified: tests/scheduler/test_run_now.py:31 — use ONLY under TYPE_CHECKING in jobs.py (manager.py will import jobs.py → circular otherwise)
from apscheduler.util import obj_to_ref                      # verified: apscheduler 3.11.2 util.py (used in tests to assert the textual ref)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class AgentSchedulerManager:                     # line 324
    registered_name: str = "scheduler_manager"   # line 336 (instance override from kwargs at line 355)
# apscheduler 3.11.2 util.obj_to_ref(obj) -> "module:qualname"; raises ValueError for lambdas/partials/nested functions
```

### Does NOT Exist
- ~~`packages/ai-parrot-server/src/parrot/scheduler/__init__.py`~~: `parrot.scheduler` is a namespace subpackage; do not create one.
- ~~`AgentSchedulerManager._run_db_schedule` / `_run_auto_task` / `_fire_coordinator`~~: created later (TASK-4064/4065). Do not call them from tests; use a stub.
- ~~`parrot.scheduler.jobs`~~: this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/jobs.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_jobs.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create `jobs.py` with the block below. *Why*: the function names and kwargs are the persisted job reference
   (`parrot.scheduler.jobs:run_db_schedule`), so they must never change once stored in Redis.
2. Fill in the three trampolines' delegation calls exactly as documented. *Why*: the manager-side names are fixed in spec §3 M3.
3. Write the tests with a `SimpleNamespace`/`AsyncMock` stub manager. *Why*: the real manager methods land in later tasks.

### `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` (CREATE)
```python
"""Picklable APScheduler entrypoints for the agent scheduler (FEAT-631).

APScheduler persists a job's callable as a textual ``module:function`` reference.
A bound method of :class:`AgentSchedulerManager` cannot be persisted (it pickles the
manager, which holds the scheduler), so every job points at one of the module-level
coroutines below. They carry only ``str`` kwargs and resolve the live manager from a
process-local registry at fire time.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Final

if TYPE_CHECKING:
    from .manager import AgentSchedulerManager

logger = logging.getLogger("Parrot.Scheduler.jobs")


class _Skipped:
    """Type of :data:`SKIPPED`; a readable repr helps in logs."""

    def __repr__(self) -> str:
        return "<SKIPPED>"


SKIPPED: Final[object] = _Skipped()
"""Returned by a trampoline when a fire was intentionally skipped (row gone, disabled or
rescheduled). ``AgentSchedulerManager.job_success`` treats it as a no-op."""

_MANAGERS: Dict[str, "AgentSchedulerManager"] = {}


def register_manager(manager: "AgentSchedulerManager") -> None:
    """Register ``manager`` under ``manager.registered_name``; the last registration wins."""
    # FILL IN: assign into _MANAGERS; logger.debug when replacing an existing different object — bounded by spec §7 "Two managers in one process"


def unregister_manager(name: str) -> None:
    """Remove the registration for ``name``; a missing name is not an error."""
    _MANAGERS.pop(name, None)


def get_manager(name: str) -> "AgentSchedulerManager":
    """Return the manager registered under ``name``.

    Raises:
        LookupError: no manager with that name is registered in this process.
    """
    # FILL IN: lookup; raise LookupError(f"No AgentSchedulerManager registered as {name!r} in this process") — bounded by test_get_manager_unknown_raises


async def run_db_schedule(manager_name: str, schedule_id: str, fingerprint: str) -> Any:
    """Entrypoint for DB-backed schedules (delegates to ``_run_db_schedule``)."""
    return await get_manager(manager_name)._run_db_schedule(schedule_id, fingerprint)


async def run_db_schedule_now(manager_name: str, schedule_id: str) -> Any:
    """Entrypoint for run-now one-shots; always releases the cross-worker run-now guard."""
    manager = get_manager(manager_name)
    try:
        return await manager._run_db_schedule(schedule_id, None, run_now=True)
    finally:
        await manager._fire_coordinator.release_running(str(schedule_id))


async def run_auto_schedule(manager_name: str, job_id: str) -> Any:
    """Entrypoint for decorator-registered ``auto_*`` jobs (delegates to ``_run_auto_task``)."""
    return await get_manager(manager_name)._run_auto_task(job_id)
```
**Why this shape**: these are the textual references persisted by the Redis jobstore (spec G4), so names and parameter
names are frozen. `run_db_schedule_now` owns the guard release that `_run_now_wrapper` (`manager.py:1582`) owns today
(spec §3 M3: `_run_now_wrapper` is removed in TASK-4065). Keep the `TYPE_CHECKING` import: `manager.py` imports this module.

### `packages/ai-parrot-server/tests/scheduler/test_jobs.py` (CREATE)
```python
"""Tests for parrot.scheduler.jobs (FEAT-631 TASK-4061)."""
import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apscheduler.util import obj_to_ref

from parrot.scheduler import jobs


@pytest.fixture
def stub_manager():
    mgr = SimpleNamespace(
        registered_name="test_jobs_mgr",
        _run_db_schedule=AsyncMock(return_value="ok"),
        _run_auto_task=AsyncMock(return_value="auto"),
        _fire_coordinator=SimpleNamespace(release_running=AsyncMock()),
    )
    jobs.register_manager(mgr)
    yield mgr
    jobs.unregister_manager("test_jobs_mgr")

# FILL IN: test_textual_refs — obj_to_ref(jobs.run_db_schedule) == "parrot.scheduler.jobs:run_db_schedule" (same for the other two)
# FILL IN: test_skipped_is_singleton_and_picklable_kwargs — pickle.dumps({"manager_name": "m", "schedule_id": "s", "fingerprint": "f"}) works
# FILL IN: test_get_manager_unknown_raises — LookupError mentioning the name
# FILL IN: test_run_db_schedule_delegates — awaited with ("sid", "fp")
# FILL IN: test_run_db_schedule_now_releases_on_success_and_failure — release_running awaited once in both cases; exception propagates
# FILL IN: test_run_auto_schedule_delegates
```
**Why**: covers spec §4 rows `test_get_manager_unknown_raises`, plus the picklability half of `test_trampoline_job_is_picklable`
(the full-job half lands in TASK-4064).

### FILL IN checklist
- [ ] `jobs.py::register_manager`: the assignment and the replace-log; bounded by spec §7
- [ ] `jobs.py::get_manager`: `LookupError` with the name; bounded by spec §3 M1 skeleton
- [ ] `test_jobs.py`: the 6 tests listed; bounded by spec §4

---

## Acceptance Criteria

- [ ] `jobs.py` exists with exactly the public names in spec §3 M1.
- [ ] `obj_to_ref` on each trampoline returns `parrot.scheduler.jobs:<name>`.
- [ ] `run_db_schedule_now` releases the guard on success and on exception.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/scheduler/jobs.py packages/ai-parrot-server/tests/scheduler/test_jobs.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_jobs.py -q`

---

## Test Specification

See the `test_jobs.py` block above. All tests are async-capable via `pytest-asyncio` (already used by `tests/scheduler/test_run_now.py`).

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug scheduler-multiworker-correctness --feature-id FEAT-631 --spec sdd/specs/scheduler-multiworker-correctness.spec.md --index sdd/tasks/index/scheduler-multiworker-correctness.json`
2. Read the spec; verify the Codebase Contract; set this task `in-progress` in the per-spec index and commit only the index.
3. Implement from the blueprint and complete every `# FILL IN:`. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit only the listed files: `feat(scheduler-multiworker-correctness): TASK-4061 — job trampolines`.
5. Close with `scripts/sdd/close_task.sh TASK-4061 scheduler-multiworker-correctness verified`, fill in the Completion Note, commit, and push.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex), orchestrated by sdd-worker
**Date**: 2026-10-05
**Notes**: jobs.py trampolines match spec M1; merge-tier validation 181 passed. Closed via close_task.sh, not finalize_task: no durable review EvidenceRef is obtainable (coder_record_review returns only a feedback_id; durable root is in the read-only primary checkout). Review recorded as coder-review ids; zero fix commits.

**Deviations from spec**: none
