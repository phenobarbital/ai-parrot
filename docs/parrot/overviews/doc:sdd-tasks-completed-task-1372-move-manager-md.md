---
type: Wiki Overview
title: 'TASK-1372: Move manager/ to satellite'
id: doc:sdd-tasks-completed-task-1372-move-manager-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 8. BotManager imports ~25 handler classes — since handlers
  already moved to satellite (TASK-1371), BotManager must follow to avoid cross-distribution
  runtime imports. All external consumers of BotManager (`app.py`, `appauto.py`) use
  TYPE_CHECKING imports. The ho
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.chat
  rel: mentions
- concept: mod:parrot.handlers.integrations
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.manager.ephemeral
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
---

# TASK-1372: Move manager/ to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1371
**Assigned-to**: unassigned

## Context
Implements Module 8. BotManager imports ~25 handler classes — since handlers already moved to satellite (TASK-1371), BotManager must follow to avoid cross-distribution runtime imports. All external consumers of BotManager (`app.py`, `appauto.py`) use TYPE_CHECKING imports. The host `manager/__init__.py` already has lazy `__getattr__` from TASK-1367.

## Scope
- `git mv` from host to `packages/ai-parrot-server/src/parrot/manager/`:
  - manager.py (BotManager — 2116 lines)
  - ephemeral.py (EphemeralRegistry, EphemeralAgentStatus)
- Host `manager/__init__.py` already has lazy `__getattr__` from TASK-1367
- Verify BotManager's handler imports resolve from satellite (handlers moved in TASK-1371)
- Verify `app.py` and `appauto.py` can import BotManager via namespace merging

**NOT in scope**: Modifying BotManager code logic, modifying app.py, modifying host `manager/__init__.py`.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | CREATE (git mv) | BotManager |
| `packages/ai-parrot-server/src/parrot/manager/ephemeral.py` | CREATE (git mv) | EphemeralRegistry |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/manager/__init__.py — current (line 1):
from .manager import BotManager
# After TASK-1367, becomes lazy __getattr__:
def __getattr__(name: str):
    if name == "BotManager":
        from parrot.manager.manager import BotManager
        return BotManager
    ...

# parrot/manager/manager.py — BotManager handler imports (lines 27-81):
from parrot.handlers.chatbot import ChatbotHandler
from parrot.handlers.bot import BotHandler
from parrot.handlers.chat import ChatHandler
from parrot.handlers.agent_talk import AgentTalk
from parrot.handlers.integrations import IntegrationsHandler
# ... ~20 more handler imports

# parrot/manager/manager.py — core imports:
from parrot.registry import AgentRegistry
from parrot.bots.orchestration import AgentCrew
from parrot.conf import settings
from parrot.auth import ...

# parrot/manager/ephemeral.py:
from pydantic import BaseModel, Field  # EphemeralAgentStatus
# EphemeralRegistry — in-memory registry
# _warm_up — coroutine for pre-loading

# External consumers (TYPE_CHECKING):
# app.py:     from parrot.manager import BotManager  (TYPE_CHECKING or runtime)
# appauto.py: from parrot.manager import BotManager  (TYPE_CHECKING or runtime)
```

### Existing Signatures to Use
```python
# parrot/manager/manager.py
class BotManager:           # line 90
    def setup(self, app):   # line 1334 — registers routes, imports handlers
    def on_startup(self):   # line 1680 — called at application startup

# parrot/manager/ephemeral.py
class EphemeralAgentStatus(BaseModel): ...  # Pydantic model
class EphemeralRegistry: ...                # in-memory agent registry
async def _warm_up(): ...                   # pre-loading coroutine
```

### Does NOT Exist
- ~~`parrot.manager.BotManager.register_routes()`~~ — route registration is inside `setup()`, not a separate method
- ~~Runtime imports of BotManager from core~~ — all consumers use TYPE_CHECKING or lazy imports
- ~~Manager files in satellite~~ — satellite manager/ directory does not exist yet

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directory exists: `packages/ai-parrot-server/src/parrot/manager/`
2. `git mv` both files:
   ```bash
   git mv packages/ai-parrot/src/parrot/manager/manager.py packages/ai-parrot-server/src/parrot/manager/manager.py
   git mv packages/ai-parrot/src/parrot/manager/ephemeral.py packages/ai-parrot-server/src/parrot/manager/ephemeral.py
   ```
3. Verify host `manager/` directory retains only `__init__.py` (with lazy __getattr__)
4. Verify BotManager's handler imports resolve:
   - Handlers are now in satellite (TASK-1371)
   - BotManager is now in satellite too
   - Both are in the same distribution, so imports work directly
5. Verify BotManager's core imports resolve:
   - `parrot.registry`, `parrot.bots.orchestration`, `parrot.conf`, `parrot.auth` — all in core
   - These resolve via PEP 420 namespace merging — no changes needed
6. Do NOT create `__init__.py` in satellite `manager/` (PEP 420)

### Key Constraints
- Do NOT create `__init__.py` in satellite `manager/` — PEP 420 namespace package
- Do NOT modify host `manager/__init__.py` — already updated in TASK-1367
- Do NOT modify `manager.py` code — only move the file
- BotManager handler imports work because both handlers and manager are now in the same satellite distribution
- Core module imports work because PEP 420 allows cross-distribution imports in the same namespace

### Dependency Chain
```
TASK-1367 (lazy __getattr__) → TASK-1371 (move handlers) → TASK-1372 (move manager)
```
BotManager MUST move after handlers because it imports ~25 handler classes. If handlers were in satellite but manager stayed in core, those imports would fail without the satellite installed.

### Post-Move Verification
```bash
# Verify host retains only __init__.py
ls packages/ai-parrot/src/parrot/manager/
# Expected: __init__.py

# Verify satellite has both files
ls packages/ai-parrot-server/src/parrot/manager/
# Expected: manager.py  ephemeral.py
```

## Acceptance Criteria
- [ ] `from parrot.manager import BotManager` resolves from satellite (via host lazy __getattr__)
- [ ] `from parrot.manager.manager import BotManager` resolves directly from satellite
- [ ] `from parrot.manager.ephemeral import EphemeralRegistry` works
- [ ] BotManager.setup(app) can import all handler classes (both in satellite)
- [ ] BotManager core imports work (parrot.registry, parrot.bots.orchestration, etc.)
- [ ] `app.py` starts successfully with satellite installed
- [ ] Host manager/ directory retains only `__init__.py`
- [ ] No `__init__.py` in satellite `manager/` (PEP 420)
- [ ] No circular import regressions
- [ ] Existing test suite passes

## Test Specification
```python
def test_bot_manager_import():
    """BotManager resolves from satellite via namespace merging."""
    from parrot.manager import BotManager
    assert BotManager is not None

def test_bot_manager_direct_import():
    """Direct import from manager.manager works."""
    from parrot.manager.manager import BotManager
    assert BotManager is not None

def test_ephemeral_import():
    """EphemeralRegistry resolves from satellite."""
    from parrot.manager.ephemeral import EphemeralRegistry
    assert EphemeralRegistry is not None

def test_ephemeral_status_import():
    """EphemeralAgentStatus Pydantic model resolves."""
    from parrot.manager.ephemeral import EphemeralAgentStatus
    assert EphemeralAgentStatus is not None

def test_bot_manager_handler_imports():
    """BotManager can import handler classes (both in satellite)."""
    from parrot.manager.manager import BotManager
    # BotManager's module-level imports of handlers should not raise
    from parrot.handlers.chatbot import ChatbotHandler
    assert ChatbotHandler is not None

def test_host_manager_only_init():
    """Host manager/ retains only __init__.py."""
    import pathlib
    host_manager = pathlib.Path("packages/ai-parrot/src/parrot/manager")
    py_files = {f.name for f in host_manager.glob("*.py")}
    assert py_files == {"__init__.py"}
```

## Agent Instructions
1. Read `manager.py` (especially lines 27-81 for handler imports) and `ephemeral.py` before moving.
2. Follow the step-by-step procedure in Implementation Notes exactly.
3. After moving, verify that `manager.py` handler imports all point to `parrot.handlers.*` (they should already — no rewriting needed since handlers are in the same namespace).
4. Run `python -c "from parrot.manager import BotManager"` to verify namespace merging works.
5. Commit with message: `sdd: move manager to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
