# TASK-2394: InProcessScheduler in core + tax-calendar reminders (Decision D1)

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2393
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** (Goal G6) under **Decision D1**.

FEAT-203 deliberately moved task scheduling out of core into
`ai-parrot-server[scheduler]`: the extra is commented out at
`packages/ai-parrot/pyproject.toml:253-254` (*"use ai-parrot-server[scheduler]
instead"*) and `parrot/scheduler/__init__.py` is a lazy shim that resolves five
symbols from the satellite via PEP 562 `__getattr__`.

The operator's decision (spec §8) is to **reactivate the extra in core** so an
agent process can schedule reminders without depending on the server
distribution. This partially reverses FEAT-203 **by decision, not by accident** —
the pyproject comment must say so and reference FEAT-453, so a future reader does
not "fix" it back.

Implements spec **Module 8**.

---

## Scope

- Reactivate the `scheduler` extra in `packages/ai-parrot/pyproject.toml`,
  pinned to `apscheduler==3.11.2` (the same version the satellite uses) to avoid
  a split-brain dependency. Replace the FEAT-203 comment with one explaining the
  FEAT-453 reversal.
- Create `parrot/scheduler/inprocess.py` with `InProcessScheduler`
  (`start`, `stop`, `add_cron`).
- **Must not shadow the satellite.** `AgentSchedulerManager`, `ScheduleType`,
  `schedule`, `schedule_daily_report` and `schedule_weekly_report` must keep
  resolving through the existing `__getattr__` in `parrot/scheduler/__init__.py`.
- Add tax-calendar reminder callbacks that create Google Calendar events
  (TASK-2393) and notify over the configured channel.
- Add the checkpoint-retention sweep from Decision D3: archive-and-alert at 90
  days, never silent deletion.

**NOT in scope**: the `SmokeCheck` runner (TASK-2395); deploying ai-parrot-server.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Reactivate the scheduler extra + FEAT-453 comment |
| `packages/ai-parrot/src/parrot/scheduler/inprocess.py` | CREATE | InProcessScheduler |
| `packages/ai-parrot/tests/scheduler/test_inprocess.py` | CREATE | Incl. no-shadowing regression |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
# NOTE: apscheduler becomes available in core only after the extra is reactivated.
from apscheduler.schedulers.asyncio import AsyncIOScheduler   # apscheduler==3.11.2
# The satellite-delegated symbols must KEEP working:
#   from parrot.scheduler import AgentSchedulerManager   # via __getattr__ -> ai-parrot-server
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/scheduler/__init__.py — THE SHIM TO PRESERVE
"""Agent Scheduler for AI-Parrot.
The scheduler implementation (AgentSchedulerManager, decorators, ScheduleType)
is part of the server layer (ai-parrot-server satellite).
Use: pip install ai-parrot-server[scheduler]"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
_SERVER_CLASSES = {
    "ScheduleType":           ("parrot.scheduler.manager", "ScheduleType"),
    "schedule":               ("parrot.scheduler.manager", "schedule"),
    "schedule_daily_report":  ("parrot.scheduler.manager", "schedule_daily_report"),
    "schedule_weekly_report": ("parrot.scheduler.manager", "schedule_weekly_report"),
    "AgentSchedulerManager":  ("parrot.scheduler.manager", "AgentSchedulerManager"),
}
def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        from parrot._imports import load_satellite_attr
        ...
    raise AttributeError(...)

# packages/ai-parrot/pyproject.toml — lines 253-254, THE TARGET
#   # Task scheduling moved to ai-parrot-server[scheduler] in FEAT-203
#   # scheduler = ["apscheduler==3.11.2"]  # use ai-parrot-server[scheduler] instead

# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py — callback shape
class BaseSchedulerCallback(NotificationMixin):     # line 16
    callback_name = "base"; description = "Base scheduler callback"
    def __init__(self, config=None, logger=None) -> None: ...   # line 22
    @classmethod
    def describe(cls) -> Dict[str, Any]: ...                    # line 27
    def process_output(self, result: Any) -> Dict[str, Any]: ...# line 34
```

### Does NOT Exist

- ~~`parrot.scheduler.manager` in CORE~~ — that module lives in the **ai-parrot-server** satellite. Do not create a core module with that name; it would shadow the satellite and break `AgentSchedulerManager` resolution.
- ~~`AgentSchedulerManager` as a core class~~ — never reimplement it here. The new class is `InProcessScheduler`, a deliberately different name.
- ~~`BaseSchedulerCallback` in core~~ — it is satellite-only (`ai-parrot-server/.../scheduler/functions/__init__.py:16`). Imitate its shape if useful; do not import it from core.

---

## Implementation Notes

### Key Constraints
- **Naming is load-bearing.** Any core symbol colliding with one of the five
  `_SERVER_CLASSES` keys breaks the satellite delegation silently for anyone who
  has ai-parrot-server installed. AC covers this with a real regression test.
- Pin `apscheduler==3.11.2` exactly — a version skew between core and satellite
  is a split-brain waiting to happen.
- The pyproject comment MUST reference FEAT-453 and say the reversal is
  deliberate.
- Retention sweep: archive-and-alert, never silent deletion (D3). A checkpoint is
  the record of what was already written to the accounting system.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] The `scheduler` extra is active in `packages/ai-parrot/pyproject.toml`, pinned to `apscheduler==3.11.2`
- [ ] The pyproject comment explains the FEAT-453 reversal of FEAT-203
- [ ] `from parrot.scheduler import AgentSchedulerManager` still resolves via the satellite `__getattr__`
- [ ] None of the five `_SERVER_CLASSES` names are shadowed by core
- [ ] A cron reminder fires and creates a calendar event
- [ ] The 90-day retention sweep archives and alerts; it never deletes silently
- [ ] All tests pass: `pytest packages/ai-parrot/tests/scheduler/test_inprocess.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest


class TestNoShadowing:
    def test_satellite_symbols_still_delegate(self):
        """Regression for Decision D1 — core must not shadow the satellite."""
        import parrot.scheduler as s
        for name in ("AgentSchedulerManager","ScheduleType","schedule",
                     "schedule_daily_report","schedule_weekly_report"):
            assert name in s.__all__
            # resolving raises ImportError-with-install-hint when the satellite
            # is absent — NOT AttributeError, and never a core stand-in.

    def test_inprocess_is_distinctly_named(self):
        from parrot.scheduler.inprocess import InProcessScheduler
        assert InProcessScheduler.__name__ != "AgentSchedulerManager"


class TestInProcessScheduler:
    async def test_add_cron_fires(self, scheduler):
        fired = []
        scheduler.add_cron("t", "* * * * *", lambda: fired.append(1))
        await scheduler.start()
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2394-inprocess-scheduler-and-tax-reminders.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
