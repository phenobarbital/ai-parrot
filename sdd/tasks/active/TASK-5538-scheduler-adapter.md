# TASK-5538: Scheduler adapter for daily live validation

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5537
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (server half) and AC15. The host application builds the scheduler (`app.py:158-163`,
`AgentSchedulerManager(...).setup(app)`, reachable as `app["scheduler_manager"]`). This task ships an adapter in
`ai-parrot-server` the host can call: an object with one `@schedule(ScheduleType.DAILY)` method that runs
`run_live_validation` on the **same** toolkit instance that serves queries, and `register_accounting_schedules`.
No host file is modified (spec §8 Q2 leaves wiring to the owner).

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` with `AccountingValidationJobs` and
  `register_accounting_schedules`, per the spec §3 M9 Interface Skeleton.
- The job lazily imports `parrot.semantic.accounting.live.run_live_validation` (the server must import without
  `ai-parrot-semantic` installed) and returns the report as a dict.
- Create `packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py`: `test_register_accounting_schedules`,
  `test_job_uses_same_toolkit`, `test_module_imports_without_semantic`.

**NOT in scope**: editing `app.py` or any host wiring; live validation logic (TASK-5537).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` | CREATE | adapter |
| `packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py` | CREATE | adapter tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.scheduler.manager import schedule                      # SRV/scheduler/manager.py:50
from parrot.scheduler.base import ScheduleType, SchedulerManager   # SRV/scheduler/base.py:91, :255
```
`SRV` = `packages/ai-parrot-server/src/parrot`.

### Existing Signatures to Use
```python
# SRV/scheduler/manager.py:50
def schedule(schedule_type: ScheduleType = ScheduleType.DAILY, *, success_callback=None, send_result=None,
             callbacks=None, **schedule_config)          # attaches _schedule_config to the method
# SRV/scheduler/base.py
class ScheduleType(Enum): ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB      # :91
class SchedulerManager:                                   # :255 — __init__(self, **kwargs) (:260)
    def register_object_schedules(self, obj: Any, name: str) -> int   # :806 — job id f"auto_{name}_{method}"
# Test precedent: packages/ai-parrot-server/tests/scheduler/test_base_crud.py:24-34 (memory_manager fixture):
#   manager = SchedulerManager(registered_name=scheduler_namespace); manager.scheduler.add_jobstore(MemoryJobStore(), alias="redis")
#   ... assert memory_manager.register_object_schedules(target, "a.b") == 1 (:92); teardown await manager.stop_headless(wait=False)
# packages/ai-parrot-server/tests/scheduler/conftest.py:19 — fixture scheduler_namespace
```

### Does NOT Exist
- ~~a `SchedulerManager(` construction in `packages/*/src`~~ — the host builds it; this adapter receives one.
- ~~`SchedulerManager.add_schedule(backend="code")`~~ — code jobs only via `register_object_schedules`.
- ~~a top-level `import parrot.semantic` in the server~~ — import lazily inside the job.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/base.py#SchedulerManager.register_object_schedules",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#schedule"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the adapter.
2. Tests: copy the `memory_manager` fixture shape from `test_base_crud.py` into this test file (do not import it).

### `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` (CREATE)
```python
"""Daily live validation of accounting models (FEAT-713 M9). The host registers it on its scheduler."""

from __future__ import annotations

import logging
from typing import Any, Callable

from parrot.scheduler.base import ScheduleType, SchedulerManager
from parrot.scheduler.manager import schedule


class AccountingValidationJobs:
    """Scheduler target; the factory must return the SAME toolkit instance that serves queries."""

    def __init__(self, toolkit_factory: Callable[[], Any]) -> None:
        self.toolkit_factory = toolkit_factory
        self.logger = logging.getLogger(__name__)

    @schedule(ScheduleType.DAILY, hour=6, minute=0)
    async def validate_accounting_models(self) -> dict:
        """Lazy-imports parrot.semantic.accounting.live; returns the report as a dict."""
        from parrot.semantic.accounting.live import run_live_validation

        report = await run_live_validation(self.toolkit_factory())
        # FILL IN: log a one-line summary (models, failures) at INFO without identities or SQL.
        return report.model_dump(mode="json")


def register_accounting_schedules(scheduler: SchedulerManager, toolkit_factory: Callable[[], Any]) -> int:
    """scheduler.register_object_schedules(AccountingValidationJobs(factory), "accounting") (verified: base.py:806)."""
    return scheduler.register_object_schedules(AccountingValidationJobs(toolkit_factory), "accounting")
```

### `packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py` (CREATE)
```python
"""FEAT-713 M9 — scheduler adapter."""

from __future__ import annotations

import pytest


async def test_register_accounting_schedules(scheduler_namespace: str) -> None:
    # FILL IN: SchedulerManager(registered_name=...) as in test_base_crud.py; register ⇒ 1; job id
    #   "auto_accounting_validate_accounting_models" exists; stop_headless(wait=False) in finally.


async def test_job_uses_same_toolkit(monkeypatch) -> None:
    # FILL IN: monkeypatch parrot.semantic.accounting.live.run_live_validation (importorskip the satellite) to record
    #   the toolkit; the job passes the factory's instance and returns a dict.


def test_module_imports_without_semantic() -> None:
    # FILL IN: importing parrot.scheduler.accounting_jobs does not import parrot.semantic.
```

### FILL IN checklist
- [ ] Summary log line; three tests.

---

## Acceptance Criteria

- [ ] `register_accounting_schedules` registers exactly one daily job on a `SchedulerManager` (AC15).
- [ ] The job runs on the factory's toolkit instance; no public trusted-bypass parameter exists (AC15).
- [ ] The server module imports without `ai-parrot-semantic`.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for `packages/ai-parrot-server/src`, `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5538 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
