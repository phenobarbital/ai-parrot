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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Reactivated the `scheduler` extra in `packages/ai-parrot/pyproject.toml`
(pinned `apscheduler==3.11.2`, matching the satellite's version) with a
comment explaining the FEAT-453/Decision D1 reversal and warning future
readers not to "fix" it back — did not touch `parrot/scheduler/__init__.py`
at all (out of this task's file list; its `_SERVER_CLASSES`/`__getattr__`
delegation is untouched, verified by direct introspection). Created
`InProcessScheduler` (`start`/`stop`/`add_cron`) in a brand-new sibling
module `parrot/scheduler/inprocess.py`. Also implemented `TaxDeadline` +
`schedule_tax_reminder()` (generic callback, not a hardcoded calendar
call — see Deviations) and `notify_tax_deadline()` for the reminder
callbacks, plus `sweep_checkpoint_retention()` for the Decision D3
90-day archive-and-alert sweep (moves aged files to an `archive/`
subdirectory — 0700 — and alerts a `HumanChannel` when anything is
archived; never deletes).

**Two real bugs found and fixed during implementation** (verified via a
standalone script — see below): (1) `AsyncIOScheduler.add_job(...,
replace_existing=True)` only dedupes reliably once the scheduler is
*running* — its pre-start "pending jobs" queue does not check for id
collisions the same way the live jobstore does, so re-registering the same
`add_cron` name before `start()` silently produced two jobs. Fixed by
having `add_cron()` track its own `name -> job` map and explicitly
`remove_job()` any prior job for that name before re-adding. (2)
`AsyncIOScheduler.shutdown()` schedules its actual work via `call_soon`
rather than completing synchronously, so gating `stop()`'s idempotency on
`self._scheduler.running` raced a second call into a `SchedulerNotRunningError`
(logged, not raised, by asyncio's callback machinery — but noisy and
non-deterministic). Fixed by tracking `self._running` as our own
independent state flag.

**Test execution note**: `pytest packages/ai-parrot/tests/scheduler/test_inprocess.py`
could not be run to completion in this worktree — `packages/ai-parrot/tests/conftest.py`'s
autouse `_reset_injection_engine_singleton` fixture pulls in
`parrot.bots`/`parrot.tools.manager`/`parrot.auth`, which transitively
imports `parrot.utils.types` and `parrot.utils.parsers.toml` — both
Cython extensions (`.pyx` sources compiled to `.so`/`.cpp`). The compiled
`.so` artifacts exist in the main repo checkout but are build outputs, not
tracked by git, and are not present in this git worktree (confirmed: this
affects `packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py`
too — a pre-existing, unrelated test file — with the identical error, and
copying just one `.so` cascades to the next missing one). This is a
pre-existing, environment/build-provisioning gap in the FEAT-145 worktree
model for Cython-backed packages, not a code defect, and out of scope for
any FEAT-453 task. Worked around it by writing a standalone async script
(bypassing `packages/ai-parrot/tests/conftest.py` entirely — my module
itself imports cleanly with only `apscheduler` + a `TYPE_CHECKING`-only
`parrot.human` reference) that exercises every scenario in
`test_inprocess.py` line-for-line (cron registration/validation/replacement/
firing, start/stop idempotency, tax-reminder scheduling + lead-day
computation + callback invocation, notify-with/without-channel, and the
full retention-sweep suite including permissions and alerting) — all
passed. All shadowing-regression assertions (`TestNoShadowing`) were also
verified directly via module introspection (no test-runner needed for
those). Full `packages/ai-parrot-tools/tests/scraping/` + `business_automation/`
+ `google/` suites (866 tests, run to confirm the `pyproject.toml` change
causes no regressions there) re-run: only the same pre-existing,
unrelated failures (`CrawlEngine`/FEAT-013, `test_places.py`'s
`ToolResult`/dict mismatch). `ruff check` clean except the same
`UP006`/`UP017`/`UP035`/`UP045` pyupgrade-style debt already established
by this feature's other files.

**Deviations from spec**: (1) `schedule_tax_reminder()` takes a generic
`on_reminder: Callable[[TaxDeadline], Awaitable[None]]` callback rather than
directly constructing/calling a `GoogleCalendarToolkit` — verified via
`grep` that `ai-parrot-tools` (which owns `GoogleCalendarToolkit`, from
TASK-2393) depends on core `ai-parrot`, never the reverse; importing it at
runtime from this core module would be a reverse/circular package
dependency. `GoogleCalendarToolkit`/`HumanChannel` are referenced only
under `TYPE_CHECKING` for documentation/type-hint purposes. The caller
(whoever assembles the final agent, per spec §2's public/private seam)
composes the closure that actually calls `create_event`/`send_notification`.
(2) No real Spanish tax deadlines are hardcoded anywhere — `TaxDeadline`
instances are supplied by the caller, consistent with the spec's own
explicit risk note that FEAT-449 (legal-norms-graph-boe) is adjacent, not
authoritative, for filing deadlines.
