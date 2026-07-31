---
type: Wiki Overview
title: 'TASK-1367: Add extend_path and lazy __getattr__ to host __init__.py files'
id: doc:sdd-tasks-completed-task-1367-add-extend-path-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 3. None of the target `__init__.py` files (mcp, a2a, handlers,
  manager, services, scheduler, autonomous) currently have `extend_path` calls. This
  task adds them and converts eager imports of server classes into lazy `__getattr__`
  patterns, so the host works both
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
---

# TASK-1367: Add extend_path and lazy __getattr__ to host __init__.py files

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1365
**Assigned-to**: unassigned

## Context
Implements Module 3. None of the target `__init__.py` files (mcp, a2a, handlers, manager, services, scheduler, autonomous) currently have `extend_path` calls. This task adds them and converts eager imports of server classes into lazy `__getattr__` patterns, so the host works both with and without the satellite installed.

## Scope
For each of these 7 files, add `from pkgutil import extend_path; __path__ = extend_path(__path__, __name__)` at the top, then convert server-side imports to lazy `__getattr__`:

1. **`parrot/mcp/__init__.py`**: Keep consumer imports (MCPClient, MCPEnabledMixin, AuthScheme, AuthCredential, ReadonlyContext, MCPSessionManager, etc.) as eager. Convert server imports to lazy: MCPServerConfig (from .config), APIKeyStore, ExternalOAuthValidator, APIKeyRecord (from .oauth — server classes moving in TASK-1368).
2. **`parrot/a2a/__init__.py`**: Keep consumer imports (A2AClient, A2AClientMixin, A2AAgentConnection, A2ARemoteAgentTool, A2ARemoteSkillTool, models, mesh, router, orchestrator) as eager. Convert server imports to lazy: A2AServer, A2AEnabledMixin (from .server), all security exports (from .security).
3. **`parrot/handlers/__init__.py`**: Add extend_path before existing `__getattr__`. Existing lazy pattern continues to work via namespace merging.
4. **`parrot/manager/__init__.py`**: Convert `from .manager import BotManager` to lazy `__getattr__`.
5. **`parrot/services/__init__.py`**: Convert all imports to lazy `__getattr__`.
6. **`parrot/scheduler/__init__.py`**: This 1740-line file will be replaced with a slim stub: extend_path + lazy exports. The original content moves in TASK-1374 — here we just prepare the stub.
7. **`parrot/autonomous/__init__.py`**: Add extend_path (currently empty file).

All lazy `__getattr__` must provide helpful error messages when `ai-parrot-server` is not installed.

**NOT in scope**: Actually moving files to satellite (done in TASK-1369–1375).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/__init__.py` | MODIFY | Add extend_path, lazy server exports |
| `packages/ai-parrot/src/parrot/a2a/__init__.py` | MODIFY | Add extend_path, lazy server exports |
| `packages/ai-parrot/src/parrot/handlers/__init__.py` | MODIFY | Add extend_path |
| `packages/ai-parrot/src/parrot/manager/__init__.py` | MODIFY | Add extend_path, lazy BotManager |
| `packages/ai-parrot/src/parrot/services/__init__.py` | MODIFY | Add extend_path, lazy exports |
| `packages/ai-parrot/src/parrot/scheduler/__init__.py` | MODIFY | Prepare slim stub (original content preserved for TASK-1374) |
| `packages/ai-parrot/src/parrot/autonomous/__init__.py` | MODIFY | Add extend_path |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Pattern from parrot/rerankers/__init__.py (proven lazy __getattr__):
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

def __getattr__(name: str):
    if name == "LocalCrossEncoderReranker":
        from parrot.rerankers.local import LocalCrossEncoderReranker
        return LocalCrossEncoderReranker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# parrot/__init__.py extend_path pattern (line 12):
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

### Existing Signatures to Use
```python
# parrot/mcp/__init__.py — current __all__ has 33 items (lines 40-72)
# parrot/a2a/__init__.py — current __all__ has 46 items (lines 190-238)
# parrot/handlers/__init__.py — __getattr__ with 14 handler types (lines 5-52)
# parrot/manager/__init__.py — from .manager import BotManager (line 1)
# parrot/services/__init__.py — 10 explicit exports (lines 18-29)
# parrot/scheduler/__init__.py — 1740 lines, ScheduleType at line 52
# parrot/autonomous/__init__.py — empty file
```

### Does NOT Exist
- ~~`parrot.mcp.__init__.py` extend_path~~ — does NOT exist yet
- ~~`parrot.a2a.__init__.py` extend_path~~ — does NOT exist yet
- ~~Any extend_path in handlers, manager, services, scheduler, autonomous __init__.py~~ — none exist yet

## Implementation Notes

### Pattern to Follow
```python
# Lazy __getattr__ with helpful error for missing satellite
_SERVER_EXPORTS = {"A2AServer", "A2AEnabledMixin"}

def __getattr__(name: str):
    if name in _SERVER_EXPORTS:
        try:
            from parrot.a2a.server import A2AServer, A2AEnabledMixin
            _mod = {"A2AServer": A2AServer, "A2AEnabledMixin": A2AEnabledMixin}
            return _mod[name]
        except ImportError:
            raise ImportError(
                f"{name} requires the ai-parrot-server package. "
                f"Install it with: pip install ai-parrot-server"
            ) from None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### Key Constraints
- MUST preserve all existing consumer exports as eager imports
- Lazy exports MUST work when satellite IS installed (via namespace merging)
- Lazy exports MUST give helpful ImportError when satellite is NOT installed
- `__all__` must be updated to include both eager and lazy exports

## Acceptance Criteria
- [ ] All 7 files have `extend_path` calls
- [ ] Consumer imports work without satellite: `from parrot.mcp import MCPClient`
- [ ] Server imports work WITH satellite: `from parrot.a2a import A2AServer`
- [ ] Server imports raise helpful ImportError WITHOUT satellite
- [ ] No circular imports introduced
- [ ] Existing test suite passes

## Test Specification
```python
def test_mcp_consumer_imports():
    """Consumer imports must work without satellite."""
    from parrot.mcp import MCPClient, MCPEnabledMixin
    assert MCPClient is not None

def test_a2a_consumer_imports():
    """Consumer imports must work without satellite."""
    from parrot.a2a import A2AClient, A2AClientMixin
    assert A2AClient is not None

def test_lazy_server_import_error():
    """Server imports raise helpful error without satellite."""
    import pytest
    with pytest.raises(ImportError, match="ai-parrot-server"):
        from parrot.a2a import A2AServer
```

## Agent Instructions
(standard — see template)

## Completion Note
*(Agent fills this in when done)*
