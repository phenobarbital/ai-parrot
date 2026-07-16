---
type: Wiki Overview
title: 'TASK-1370: Move A2A server files to satellite'
id: doc:sdd-tasks-completed-task-1370-move-a2a-server-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 6. Cleanest extraction — A2A server files use only TYPE_CHECKING
  imports to core. No other core module imports from `parrot.a2a.server` or `parrot.a2a.security`
  at runtime. The lazy `__getattr__` in host `a2a/__init__.py` (set up in TASK-1367)
  will resolve satel
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.a2a.client
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.security
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1370: Move A2A server files to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1367
**Assigned-to**: unassigned

## Context
Implements Module 6. Cleanest extraction — A2A server files use only TYPE_CHECKING imports to core. No other core module imports from `parrot.a2a.server` or `parrot.a2a.security` at runtime. The lazy `__getattr__` in host `a2a/__init__.py` (set up in TASK-1367) will resolve satellite classes via PEP 420 namespace merging.

## Scope
- `git mv` from host to `packages/ai-parrot-server/src/parrot/a2a/`:
  - server.py (A2AServer, A2AEnabledMixin — 771 lines)
  - security.py (A2ASecurityMiddleware, JWTAuthenticator, MTLSAuthenticator, etc. — 1984 lines)
- Verify TYPE_CHECKING imports to `..bots.abstract.AbstractBot` and `..tools.abstract.AbstractTool` still resolve
- Verify lazy `__getattr__` in host `a2a/__init__.py` resolves satellite classes

**NOT in scope**: Modifying host `__init__.py` (TASK-1367), modifying consumer files, moving models.py or client.py.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | CREATE (git mv) | A2AServer, A2AEnabledMixin |
| `packages/ai-parrot-server/src/parrot/a2a/security.py` | CREATE (git mv) | A2ASecurityMiddleware + auth |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/a2a/server.py — TYPE_CHECKING imports only to core
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..bots.abstract import AbstractBot
    from ..tools.abstract import AbstractTool

# parrot/a2a/server.py — runtime imports from sibling modules
from .models import AgentCard, Task, Message, TaskState, ...

# parrot/a2a/security.py — TYPE_CHECKING imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .server import A2AServer    # will be a local import in satellite
    from .client import A2AClient    # still in core, resolves via namespace

# parrot/a2a/security.py — runtime imports (external packages)
# aiohttp, PyJWT (optional), redis.asyncio (optional)
# NO runtime imports from parrot.bots, parrot.tools, etc.

# parrot/a2a/models.py — pure dataclasses, NO external deps, stays in core
# parrot/a2a/client.py — stays in core, imports from .models
```

### Existing Signatures to Use
```python
# parrot/a2a/server.py
class A2AServer: ...          # main A2A server class
class A2AEnabledMixin: ...    # mixin for enabling A2A on agents

# parrot/a2a/security.py
class A2ASecurityMiddleware: ...   # aiohttp middleware
class JWTAuthenticator: ...        # JWT-based auth
class MTLSAuthenticator: ...       # mutual TLS auth
```

### Does NOT Exist
- ~~Runtime imports from a2a/server.py to core modules~~ — all are TYPE_CHECKING only
- ~~Other parrot modules importing from parrot.a2a.server~~ — only examples/tests reference it
- ~~A2A server files in satellite~~ — satellite a2a/ directory does not exist yet

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directory exists: `packages/ai-parrot-server/src/parrot/a2a/`
2. `git mv` both files:
   ```bash
   git mv packages/ai-parrot/src/parrot/a2a/server.py packages/ai-parrot-server/src/parrot/a2a/server.py
   git mv packages/ai-parrot/src/parrot/a2a/security.py packages/ai-parrot-server/src/parrot/a2a/security.py
   ```
3. In `server.py`, convert relative TYPE_CHECKING imports to absolute:
   ```python
   # Before (relative — breaks after move to satellite)
   if TYPE_CHECKING:
       from ..bots.abstract import AbstractBot
       from ..tools.abstract import AbstractTool

   # After (absolute — works from any namespace package location)
   if TYPE_CHECKING:
       from parrot.bots.abstract import AbstractBot
       from parrot.tools.abstract import AbstractTool
   ```
4. In `server.py`, convert relative `.models` import to absolute:
   ```python
   # Before
   from .models import AgentCard, Task, ...

   # After (models stays in core, resolved via namespace)
   from parrot.a2a.models import AgentCard, Task, ...
   ```
5. In `security.py`, convert relative imports similarly:
   ```python
   # TYPE_CHECKING imports
   from parrot.a2a.server import A2AServer      # now local in satellite
   from parrot.a2a.client import A2AClient      # in core, via namespace
   ```
6. Verify no `__init__.py` is created in satellite `a2a/` (PEP 420)

### Key Constraints
- Do NOT create `__init__.py` in satellite `a2a/` — PEP 420 namespace package
- Do NOT modify host `a2a/__init__.py` — already updated in TASK-1367
- TYPE_CHECKING imports must be converted from relative to absolute since the files move to a different distribution
- Runtime imports from `.models` must also become absolute since models.py stays in core

## Acceptance Criteria
- [ ] `from parrot.a2a import A2AServer` resolves from satellite (via lazy __getattr__ in host)
- [ ] `from parrot.a2a.security import A2ASecurityMiddleware` works
- [ ] `from parrot.a2a import A2AClient` still works (core, eager import)
- [ ] `from parrot.a2a import AgentCard, Task, Message` still works (core)
- [ ] TYPE_CHECKING imports in moved files use absolute paths
- [ ] Runtime imports from `.models` use absolute `parrot.a2a.models` paths
- [ ] No `__init__.py` in satellite `a2a/` (PEP 420)
- [ ] No circular imports introduced
- [ ] Existing test suite passes

## Test Specification
```python
def test_a2a_server_import_from_satellite():
    """A2AServer resolves from satellite via namespace merging."""
    from parrot.a2a import A2AServer
    assert A2AServer is not None

def test_a2a_security_import():
    """A2ASecurityMiddleware resolves from satellite."""
    from parrot.a2a.security import A2ASecurityMiddleware
    assert A2ASecurityMiddleware is not None

def test_a2a_client_still_in_core():
    """Consumer imports still work from core."""
    from parrot.a2a import A2AClient, A2AClientMixin
    assert A2AClient is not None

def test_a2a_models_still_in_core():
    """Model imports still work from core."""
    from parrot.a2a import AgentCard, Task, Message
    assert AgentCard is not None

def test_server_no_relative_imports():
    """Moved files use absolute imports, not relative."""
    import pathlib
    satellite_a2a = pathlib.Path("packages/ai-parrot-server/src/parrot/a2a")
    for py_file in satellite_a2a.glob("*.py"):
        content = py_file.read_text()
        assert "from .." not in content, f"{py_file} still has relative imports to parent packages"
```

## Agent Instructions
1. Read both files (`server.py`, `security.py`) in full before making changes.
2. Follow the step-by-step procedure in Implementation Notes exactly.
3. After moving, grep both files for any remaining relative imports (`from .` or `from ..`) and convert to absolute.
4. Run `python -c "from parrot.a2a import A2AServer"` to verify namespace merging works.
5. Commit with message: `sdd: move A2A server files to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
