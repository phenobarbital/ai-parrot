---
type: Wiki Overview
title: 'TASK-1374: Move scheduler/ to satellite'
id: doc:sdd-tasks-completed-task-1374-move-scheduler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 10. The current `scheduler/__init__.py` is a 1740-line
  file containing the entire `AgentSchedulerManager`. Its content must be moved to
  `manager.py` in the satellite, while the host `__init__.py` becomes a slim stub
  (already prepared in TASK-1367).
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.notifications
  rel: mentions
- concept: mod:parrot.scheduler
  rel: mentions
- concept: mod:parrot.scheduler.functions
  rel: mentions
- concept: mod:parrot.scheduler.manager
  rel: mentions
- concept: mod:parrot.scheduler.models
  rel: mentions
---

# TASK-1374: Move scheduler/ to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1367
**Assigned-to**: unassigned

## Context
Implements Module 10. The current `scheduler/__init__.py` is a 1740-line file containing the entire `AgentSchedulerManager`. Its content must be moved to `manager.py` in the satellite, while the host `__init__.py` becomes a slim stub (already prepared in TASK-1367).

## Scope
- Move content of `parrot/scheduler/__init__.py` (1740 lines) to `packages/ai-parrot-server/src/parrot/scheduler/manager.py`
- `git mv` `parrot/scheduler/models.py` to satellite
- `git mv` `parrot/scheduler/functions/` (entire directory) to satellite
- Host `scheduler/__init__.py` is already a slim stub from TASK-1367
- Note: `github_reviewer.py` and `jira_specialist.py` import `@schedule_daily_report` / `@schedule_weekly_report` — these bots become server-only

**NOT in scope**: Modifying the bots that import decorators.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | CREATE | Content from host `__init__.py` (1740 lines) |
| `packages/ai-parrot-server/src/parrot/scheduler/models.py` | CREATE (git mv) | AgentSchedule ORM |
| `packages/ai-parrot-server/src/parrot/scheduler/functions/` | CREATE (git mv) | Callback registry |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/scheduler/__init__.py contains ALL of the following:
# - ScheduleType enum (line 52)
# - schedule decorator (line 64)
# - schedule_daily_report decorator (line 145)
# - schedule_weekly_report decorator (line 164)
# - AgentSchedulerManager class (line 284)

from parrot.scheduler import AgentSchedulerManager
from parrot.scheduler import schedule, ScheduleType
from parrot.scheduler import schedule_daily_report, schedule_weekly_report

# parrot/scheduler/models.py — AgentSchedule dataclass
from parrot.scheduler.models import AgentSchedule

# parrot/scheduler/functions/__init__.py — BaseSchedulerCallback, CALLBACK_REGISTRY, build_scheduler_callback
from parrot.scheduler.functions import build_scheduler_callback

# Imports used by scheduler/__init__.py:
# apscheduler (lines 17-34)
# aiohttp.web
# navconfig
# asyncdb
# navigator.connections.PostgresPool
# parrot.conf
# parrot.notifications
```

### Does NOT Exist
- ~~`parrot.scheduler.manager`~~ — does not exist yet; created from `__init__.py` content
- ~~Separate file for decorators~~ — `schedule`/`schedule_daily_report`/`schedule_weekly_report` are ALL in `__init__.py`

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directory exists:
   ```bash
   mkdir -p packages/ai-parrot-server/src/parrot/scheduler/
   ```
2. Copy the full content of host `scheduler/__init__.py` (1740 lines) into satellite `manager.py`:
   ```bash
   cp packages/ai-parrot/src/parrot/scheduler/__init__.py packages/ai-parrot-server/src/parrot/scheduler/manager.py
   ```
   Then edit `manager.py` to adjust any relative imports as needed.
3. `git mv` models and functions:
   ```bash
   git mv packages/ai-parrot/src/parrot/scheduler/models.py packages/ai-parrot-server/src/parrot/scheduler/models.py
   git mv packages/ai-parrot/src/parrot/scheduler/functions/ packages/ai-parrot-server/src/parrot/scheduler/functions/
   ```
4. Verify host `scheduler/__init__.py` is already the slim stub from TASK-1367 (with lazy `__getattr__` re-exporting `AgentSchedulerManager`, `schedule`, `ScheduleType`, `schedule_daily_report`, `schedule_weekly_report`)
5. Verify the satellite `manager.py` imports resolve correctly — especially relative imports to `models` and `functions`

### Key Constraints
- Do NOT create `__init__.py` in satellite `scheduler/` — PEP 420 namespace package
- Do NOT modify host `scheduler/__init__.py` — already updated with lazy `__getattr__` in TASK-1367
- The 1740-line `__init__.py` contains classes, decorators, and enums — all must land in `manager.py`
- The lazy `__getattr__` in host must re-export from `parrot.scheduler.manager` transparently
- `functions/` directory has its own `__init__.py` (it is an internal package, not a namespace package) — preserve it

### Import Rewrite Map
| Old Import (internal to scheduler) | New Import (in manager.py) |
|---|---|
| `from .models import AgentSchedule` | `from parrot.scheduler.models import AgentSchedule` (or keep relative) |
| `from .functions import build_scheduler_callback` | `from parrot.scheduler.functions import build_scheduler_callback` (or keep relative) |

## Acceptance Criteria
- [ ] `from parrot.scheduler import AgentSchedulerManager` resolves from satellite
- [ ] `from parrot.scheduler import schedule, ScheduleType` works
- [ ] `from parrot.scheduler import schedule_daily_report, schedule_weekly_report` works
- [ ] `from parrot.scheduler.models import AgentSchedule` works
- [ ] `from parrot.scheduler.functions import build_scheduler_callback` works
- [ ] No `__init__.py` in satellite `scheduler/` (PEP 420)
- [ ] Existing test suite passes

## Test Specification
```python
def test_scheduler_manager_import():
    """AgentSchedulerManager resolves from satellite."""
    from parrot.scheduler import AgentSchedulerManager
    assert AgentSchedulerManager is not None

def test_schedule_decorator_import():
    """Schedule decorators resolve from satellite."""
    from parrot.scheduler import schedule, ScheduleType
    assert schedule is not None
    assert ScheduleType is not None

def test_daily_weekly_decorators():
    """Daily/weekly report decorators resolve from satellite."""
    from parrot.scheduler import schedule_daily_report, schedule_weekly_report
    assert schedule_daily_report is not None
    assert schedule_weekly_report is not None

def test_scheduler_models_import():
    """AgentSchedule model resolves from satellite."""
    from parrot.scheduler.models import AgentSchedule
    assert AgentSchedule is not None

def test_scheduler_functions_import():
    """Scheduler functions resolve from satellite."""
    from parrot.scheduler.functions import build_scheduler_callback
    assert build_scheduler_callback is not None

def test_manager_file_in_satellite():
    """manager.py exists in satellite scheduler/."""
    import pathlib
    manager = pathlib.Path("packages/ai-parrot-server/src/parrot/scheduler/manager.py")
    assert manager.exists(), "manager.py missing from satellite"
```

## Agent Instructions
1. Read the full host `scheduler/__init__.py` before making changes — understand its 1740-line structure.
2. Read `scheduler/models.py` and `scheduler/functions/__init__.py` to understand internal imports.
3. Follow the step-by-step procedure in Implementation Notes exactly.
4. After creating `manager.py`, verify all internal imports within it resolve correctly.
5. Run `python -c "from parrot.scheduler import AgentSchedulerManager"` to verify namespace merging works.
6. Commit with message: `sdd: move scheduler to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
