---
type: Wiki Overview
title: 'TASK-1597: Package Wiring & Opt-in'
id: doc:sdd-tasks-completed-task-1597-package-wiring-optin-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Integration task that wires all FULL mode components together: updates'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
---

# TASK-1597: Package Wiring & Opt-in

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1591, TASK-1592, TASK-1593, TASK-1594, TASK-1595, TASK-1596
**Assigned-to**: unassigned

---

## Context

Integration task that wires all FULL mode components together: updates
`__init__.py` re-exports, extends the opt-in gate for FULL mode, registers
handler routes in the server, and verifies the end-to-end import chain.

This task runs after all other implementation tasks are complete and ensures
everything is properly connected.

Implements spec §3 Module 7.

---

## Scope

- Update `parrot/integrations/liveavatar/__init__.py` to re-export all FULL mode symbols:
  `FullModeConfig`, `FullModeSessionHandle`, `TenantAvatarConfig`,
  `resolve_fullmode_config`, `FullModeRoomObserver`.
- Extend `optin.py` with FULL mode variant: `is_fullmode_enabled(tenant_id) -> bool`.
  Uses `LIVEAVATAR_FULLMODE_ENABLED_TENANTS` env var (comma-separated list, `"*"` = all).
- Register `avatar_fullmode.py` routes in the server's route configuration.
- Verify all imports resolve correctly.
- Write integration-level import tests.

**NOT in scope**: Implementation of any new classes (those are in TASK-1591 through TASK-1596).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export FULL mode symbols |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py` | MODIFY | Add `is_fullmode_enabled()` |
| `packages/ai-parrot-server/src/parrot/handlers/__init__.py` | MODIFY | Register fullmode routes |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_optin.py` | MODIFY | Add tests for fullmode opt-in |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py
# Currently exports (line 10-11):
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py
def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str] = None) -> bool:  # line 58
    # Pattern to follow for is_fullmode_enabled()
```

### Does NOT Exist
- ~~`is_fullmode_enabled()`~~ — does not exist yet; this task creates it
- ~~`LIVEAVATAR_FULLMODE_ENABLED_TENANTS`~~ — env var not read yet; this task adds it

---

## Implementation Notes

### Pattern to Follow
```python
# In optin.py, add alongside is_avatar_enabled:
def is_fullmode_enabled(
    *,
    tenant_id: Optional[str],
    agent_name: Optional[str] = None,
) -> bool:
    """Check if FULL mode is enabled for a tenant."""
    if not is_avatar_enabled(tenant_id=tenant_id, agent_name=agent_name):
        return False
    allowed = os.environ.get("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "")
    if allowed == "*":
        return True
    if not allowed:
        return False
    return tenant_id in {t.strip() for t in allowed.split(",")}
```

### Key Constraints
- `is_fullmode_enabled()` is a superset of `is_avatar_enabled()` — if avatar is
  disabled globally, fullmode is also disabled
- Re-exports in `__init__.py` must not break existing imports
- Route registration must follow the server's existing pattern

---

## Acceptance Criteria

- [ ] All FULL mode symbols importable from `parrot.integrations.liveavatar`
- [ ] `is_fullmode_enabled()` returns `True` only when both avatar and fullmode gates pass
- [ ] `LIVEAVATAR_FULLMODE_ENABLED_TENANTS="*"` enables for all tenants
- [ ] Empty env var disables fullmode for all tenants
- [ ] Fullmode handler routes are registered in the server
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_optin.py -v`

---

## Test Specification

```python
import pytest
from parrot.integrations.liveavatar.optin import is_fullmode_enabled


class TestIsFullmodeEnabled:
    def test_disabled_when_avatar_disabled(self, monkeypatch):
        monkeypatch.delenv("LIVEAVATAR_ENABLED_TENANTS", raising=False)
        assert is_fullmode_enabled(tenant_id="acme") is False

    def test_disabled_when_fullmode_not_set(self, monkeypatch):
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.delenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", raising=False)
        assert is_fullmode_enabled(tenant_id="acme") is False

    def test_wildcard_enables_all(self, monkeypatch):
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "*")
        assert is_fullmode_enabled(tenant_id="acme") is True

    def test_specific_tenant_match(self, monkeypatch):
        monkeypatch.setenv("LIVEAVATAR_ENABLED_TENANTS", "*")
        monkeypatch.setenv("LIVEAVATAR_FULLMODE_ENABLED_TENANTS", "acme,beta")
        assert is_fullmode_enabled(tenant_id="acme") is True
        assert is_fullmode_enabled(tenant_id="other") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 7
2. **Check dependencies** — ALL prior tasks (1591-1596) must be completed
3. **Verify what's already exported** in `__init__.py` — don't duplicate
4. **Add `is_fullmode_enabled()`** to `optin.py`
5. **Register routes** in server handler setup
6. **Run import verification tests** and acceptance criteria

---

## Completion Note

Implemented by sdd-worker (2026-06-19):

- `__init__.py`: added exports for `FullModeRoomObserver` and `resolve_fullmode_config`
  (all FULL mode symbols now importable from `parrot.integrations.liveavatar`).
- `optin.py`: added `is_fullmode_enabled(*, tenant_id, agent_name=None) -> bool` as a
  superset gate over `is_avatar_enabled`. Reads `LIVEAVATAR_FULLMODE_ENABLED_TENANTS`
  (default-deny; `"*"` wildcard; comma-separated list). Fully documented with TODO
  Q-tenant note.
- `test_optin.py`: added `TestIsFullmodeEnabled` class with 8 test cases covering
  disabled-avatar, disabled-fullmode, wildcard, specific-tenant, agent-name propagation,
  None/empty tenant_id, and whitespace-in-list edge cases.
- `manager.py`: added `_register_fullmode_avatar_routes()` method (mirrors
  `_register_avatar_routes` pattern) and wired it in `_setup_routes()` after the LITE
  avatar routes. The `handlers/__init__.py` listed in the task does not exist in this
  project; manager.py is the correct registration point per project architecture.

Note: `packages/ai-parrot-server/src/parrot/handlers/__init__.py` does not exist in
this project — route registration follows the manager.py pattern established by
FEAT-242. Modified manager.py instead as the architecturally correct location.
