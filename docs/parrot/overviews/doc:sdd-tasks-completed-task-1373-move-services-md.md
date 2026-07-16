---
type: Wiki Overview
title: 'TASK-1373: Move services/ to satellite'
id: doc:sdd-tasks-completed-task-1373-move-services-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 9. Moves all service files except `services/mcp/` (already
  consolidated into `parrot/mcp/` by TASK-1369) from the host to the satellite package.
relates_to:
- concept: mod:parrot.services
  rel: mentions
- concept: mod:parrot.services.client
  rel: mentions
- concept: mod:parrot.services.models
  rel: mentions
---

# TASK-1373: Move services/ to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1367, TASK-1369
**Assigned-to**: unassigned

## Context
Implements Module 9. Moves all service files except `services/mcp/` (already consolidated into `parrot/mcp/` by TASK-1369) from the host to the satellite package.

## Scope
- `git mv` the following files to `packages/ai-parrot-server/src/parrot/services/`:
  - agent_service.py
  - client.py
  - delivery.py
  - heartbeat.py
  - redis_listener.py
  - task_queue.py
  - worker_pool.py
  - models.py
  - whatsapp.py
  - o365_remote_auth.py
  - identity_mapping.py
  - vault_token_sync.py
- Remove empty `services/mcp/` directory from host (already consolidated in TASK-1369)
- Host `services/__init__.py` already has lazy `__getattr__` from TASK-1367

**NOT in scope**: services/mcp/ (handled by TASK-1369).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/agent_service.py` | CREATE (git mv) | AgentService |
| `packages/ai-parrot-server/src/parrot/services/client.py` | CREATE (git mv) | AgentServiceClient |
| `packages/ai-parrot-server/src/parrot/services/delivery.py` | CREATE (git mv) | Delivery service |
| `packages/ai-parrot-server/src/parrot/services/heartbeat.py` | CREATE (git mv) | Heartbeat monitor |
| `packages/ai-parrot-server/src/parrot/services/redis_listener.py` | CREATE (git mv) | Redis pub/sub listener |
| `packages/ai-parrot-server/src/parrot/services/task_queue.py` | CREATE (git mv) | Task queue |
| `packages/ai-parrot-server/src/parrot/services/worker_pool.py` | CREATE (git mv) | Worker pool |
| `packages/ai-parrot-server/src/parrot/services/models.py` | CREATE (git mv) | Service models |
| `packages/ai-parrot-server/src/parrot/services/whatsapp.py` | CREATE (git mv) | WhatsApp bridge handlers |
| `packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py` | CREATE (git mv) | O365 remote auth |
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | CREATE (git mv) | Identity mapping |
| `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | CREATE (git mv) | Vault token sync |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/services/__init__.py — exports AgentService, AgentServiceClient, models (lines 5-29)
# After TASK-1367 this becomes lazy __getattr__ in host
from parrot.services import AgentService
from parrot.services.client import AgentServiceClient

# parrot/services/agent_service.py imports:
from ..manager import BotManager  # TYPE_CHECKING
from ..bots.abstract import AbstractBot
from ..notifications import ...
from ..conf import ...

# parrot/services/whatsapp.py — aiohttp REST handlers for WhatsApp bridge

# parrot/services/heartbeat.py — uses APScheduler (lazy import, optional)
```

### Does NOT Exist
- ~~services/mcp/ in satellite~~ — consolidated into `parrot/mcp/` in TASK-1369
- ~~services/__init__.py in satellite~~ — PEP 420 namespace package, no __init__.py

## Implementation Notes

### Step-by-Step Procedure
1. Ensure satellite directory exists:
   ```bash
   mkdir -p packages/ai-parrot-server/src/parrot/services/
   ```
2. `git mv` each service file from host to satellite:
   ```bash
   git mv packages/ai-parrot/src/parrot/services/agent_service.py packages/ai-parrot-server/src/parrot/services/agent_service.py
   git mv packages/ai-parrot/src/parrot/services/client.py packages/ai-parrot-server/src/parrot/services/client.py
   git mv packages/ai-parrot/src/parrot/services/delivery.py packages/ai-parrot-server/src/parrot/services/delivery.py
   git mv packages/ai-parrot/src/parrot/services/heartbeat.py packages/ai-parrot-server/src/parrot/services/heartbeat.py
   git mv packages/ai-parrot/src/parrot/services/redis_listener.py packages/ai-parrot-server/src/parrot/services/redis_listener.py
   git mv packages/ai-parrot/src/parrot/services/task_queue.py packages/ai-parrot-server/src/parrot/services/task_queue.py
   git mv packages/ai-parrot/src/parrot/services/worker_pool.py packages/ai-parrot-server/src/parrot/services/worker_pool.py
   git mv packages/ai-parrot/src/parrot/services/models.py packages/ai-parrot-server/src/parrot/services/models.py
   git mv packages/ai-parrot/src/parrot/services/whatsapp.py packages/ai-parrot-server/src/parrot/services/whatsapp.py
   git mv packages/ai-parrot/src/parrot/services/o365_remote_auth.py packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py
   git mv packages/ai-parrot/src/parrot/services/identity_mapping.py packages/ai-parrot-server/src/parrot/services/identity_mapping.py
   git mv packages/ai-parrot/src/parrot/services/vault_token_sync.py packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
   ```
3. Remove empty `services/mcp/` directory from host (if still present after TASK-1369):
   ```bash
   rm -rf packages/ai-parrot/src/parrot/services/mcp/
   ```
4. Verify host `services/__init__.py` has lazy `__getattr__` (from TASK-1367) and nothing else
5. Grep moved files for any stale relative imports that need updating

### Key Constraints
- Do NOT create `__init__.py` in satellite `services/` — PEP 420 namespace package
- Do NOT modify host `services/__init__.py` — already updated with lazy `__getattr__` in TASK-1367
- `heartbeat.py` uses APScheduler as an optional/lazy import — do not add hard dependency
- `agent_service.py` uses `TYPE_CHECKING` for `BotManager` — preserve this pattern

## Acceptance Criteria
- [ ] `from parrot.services import AgentService` resolves from satellite
- [ ] `from parrot.services.client import AgentServiceClient` works
- [ ] `services/mcp/` no longer exists in host
- [ ] All service internal imports work
- [ ] No `__init__.py` in satellite `services/` (PEP 420)
- [ ] Existing test suite passes

## Test Specification
```python
def test_agent_service_import():
    """AgentService resolves from satellite."""
    from parrot.services import AgentService
    assert AgentService is not None

def test_agent_service_client_import():
    """AgentServiceClient resolves from satellite."""
    from parrot.services.client import AgentServiceClient
    assert AgentServiceClient is not None

def test_models_import():
    """Service models resolve from satellite."""
    from parrot.services.models import ...
    # verify models are importable

def test_no_services_mcp_in_host():
    """services/mcp/ no longer exists in host."""
    import pathlib
    host_mcp = pathlib.Path("packages/ai-parrot/src/parrot/services/mcp")
    assert not host_mcp.exists(), "services/mcp/ should have been removed"

def test_all_service_files_in_satellite():
    """All moved service files exist in satellite."""
    import pathlib
    satellite = pathlib.Path("packages/ai-parrot-server/src/parrot/services")
    expected = [
        "agent_service.py", "client.py", "delivery.py", "heartbeat.py",
        "redis_listener.py", "task_queue.py", "worker_pool.py", "models.py",
        "whatsapp.py", "o365_remote_auth.py", "identity_mapping.py",
        "vault_token_sync.py",
    ]
    for f in expected:
        assert (satellite / f).exists(), f"{f} missing from satellite"
```

## Agent Instructions
1. Read all files listed in "Files to Create / Modify" before making changes.
2. Follow the step-by-step procedure in Implementation Notes exactly.
3. After moving files, grep the satellite services/ directory for stale import paths and fix them.
4. Run `python -c "from parrot.services import AgentService"` to verify namespace merging works.
5. Commit with message: `sdd: move services to satellite for ai-parrot-server`

## Completion Note
*(Agent fills this in when done)*
