# TASK-612: Route Registration & Package Exports

**Feature**: vectorstore-handler-api
**Spec**: `sdd/specs/vectorstore-handler-api.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-607, TASK-608, TASK-609, TASK-610, TASK-611
**Assigned-to**: unassigned

---

## Context

> Final integration task for FEAT-087. Wires up the VectorStoreHandler into the
> application by registering it in `app.py` and adding lazy imports in the handlers
> package `__init__.py`. Also fills in `parrot/handlers/stores/__init__.py` with
> the proper exports.
> Implements Spec Module 6.

---

## Scope

- Update `packages/ai-parrot/src/parrot/handlers/stores/__init__.py`:
  - Add lazy imports for `VectorStoreHandler` and `VectorStoreHelper`
- Update `packages/ai-parrot/src/parrot/handlers/__init__.py`:
  - Add lazy import for `VectorStoreHandler` following existing `__getattr__` pattern
- Update `app.py`:
  - Import and call `VectorStoreHandler.setup(self.app)` in the `configure()` method
- Verify all routes work end-to-end by confirming route registration

**NOT in scope**: handler implementation (already done), test implementation (already done)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/stores/__init__.py` | MODIFY | Add exports |
| `packages/ai-parrot/src/parrot/handlers/__init__.py` | MODIFY | Add lazy import |
| `app.py` | MODIFY | Register VectorStoreHandler.setup(app) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/handlers/stores/ — created in earlier tasks
from parrot.handlers.stores.handler import VectorStoreHandler      # TASK-608
from parrot.handlers.stores.helpers import VectorStoreHelper       # TASK-607
```

### Existing Signatures to Use
```python
# parrot/handlers/__init__.py — lazy import pattern (lines 5-46)
def __getattr__(name: str):
    """Lazy imports for handlers that may cause circular imports."""
    if name == "ChatbotHandler":
        from .bots import ChatbotHandler
        return ChatbotHandler
    if name == "DashboardHandler":
        from .dashboard_handler import DashboardHandler
        return DashboardHandler
    # ... etc

# app.py — route registration patterns (lines 89-189)
# Pattern 1: Using setup() classmethod
VideoReelHandler.setup(self.app)
ScrapingHandler.setup(self.app)

# Pattern 2: Using add_view()
self.app.router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
```

### Does NOT Exist
- ~~`VectorStoreHandler.configure(app, path)`~~ — uses `setup(app)` pattern, not `configure()`
- ~~`parrot.handlers.VectorStoreHandler`~~ — does not exist in `__init__.py` yet; this task adds it

---

## Implementation Notes

### Pattern to Follow

**stores/__init__.py:**
```python
"""Vector Store Handler API package."""
from .handler import VectorStoreHandler
from .helpers import VectorStoreHelper

__all__ = ["VectorStoreHandler", "VectorStoreHelper"]
```

**handlers/__init__.py — add to existing `__getattr__`:**
```python
if name == "VectorStoreHandler":
    from .stores import VectorStoreHandler
    return VectorStoreHandler
```

**app.py — add in configure() method:**
```python
from parrot.handlers.stores import VectorStoreHandler
VectorStoreHandler.setup(self.app)
```

### Key Constraints
- Place the `VectorStoreHandler.setup()` call near other `.setup()` calls in `app.py`
- The lazy import in `handlers/__init__.py` must follow the exact `__getattr__` pattern used by other handlers
- `stores/__init__.py` can use direct imports (not lazy) since it's a leaf package

### References in Codebase
- `packages/ai-parrot/src/parrot/handlers/__init__.py` — existing lazy import pattern
- `app.py:89-189` — existing route registration
- `packages/ai-parrot/src/parrot/handlers/scraping/__init__.py` — package init pattern

---

## Acceptance Criteria

- [ ] `from parrot.handlers.stores import VectorStoreHandler, VectorStoreHelper` works
- [ ] `from parrot.handlers import VectorStoreHandler` works (via lazy import)
- [ ] `VectorStoreHandler.setup(app)` is called in `app.py`
- [ ] Routes `/api/v1/ai/stores` and `/api/v1/ai/stores/jobs/{job_id}` are registered
- [ ] No import errors on application startup

---

## Test Specification

```python
# Verification can be done via manual inspection or a simple import test
def test_imports():
    from parrot.handlers.stores import VectorStoreHandler, VectorStoreHelper
    assert VectorStoreHandler is not None
    assert VectorStoreHelper is not None

def test_lazy_import():
    from parrot.handlers import VectorStoreHandler
    assert VectorStoreHandler is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-607 through TASK-611 are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-612-route-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet)
**Date**: 2026-04-07
**Notes**: Updated stores/__init__.py with direct exports. Added VectorStoreHandler lazy import to handlers/__init__.py. Registered VectorStoreHandler.setup(self.app) in app.py.

**Deviations from spec**: none
