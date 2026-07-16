---
type: Wiki Overview
title: 'TASK-1406: Grant Exports & Wiring'
id: doc:sdd-tasks-completed-task-1406-grant-exports-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This final task wires the new grant subsystem into the public API by exporting
relates_to:
- concept: mod:parrot.auth
  rel: mentions
---

# TASK-1406: Grant Exports & Wiring

**Feature**: FEAT-211 — Tool Grants & Bounded Approval Windows
**Spec**: `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1405
**Assigned-to**: unassigned

---

## Context

> Spec Module 4: Wiring + exports.

This final task wires the new grant subsystem into the public API by exporting
all new types from `parrot.auth.__init__` and verifying the full end-to-end
flow. It also runs the complete test suite to confirm zero regressions.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/auth/__init__.py`:
  - Add imports from `.grants`: `Grant`, `GrantConfig`, `GrantStore`,
    `InMemoryGrantStore`, `GrantGuard`, `GuardDecision`.
  - Add them to `__all__`.
- Run the full test suite to confirm zero regressions.
- Verify the complete import chain works:
  `from parrot.auth import Grant, GrantStore, InMemoryGrantStore, GrantGuard, GrantConfig, GuardDecision`.

**NOT in scope**:
- Implementing Grant/GrantStore/GrantGuard (TASK-1403, TASK-1404)
- ToolManager integration (TASK-1405)
- Redis backend or ledger integration (future features)
- Documentation beyond inline docstrings (already in code)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | Add grant imports + __all__ entries |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/auth/__init__.py — current state:
from .context import UserContext
from .permission import PermissionContext, UserSession
from .resolver import (
    AbstractPermissionResolver,
    AllowAllResolver,
    DefaultPermissionResolver,
    DenyAllResolver,
    PBACPermissionResolver,
)
from .pbac import setup_pbac
from .dataset_guard import DatasetPolicyGuard
from .models import PolicyRuleConfig
from .exceptions import AuthorizationRequired
from .agent_guard import AgentAccessDenied
from .credentials import (
    CredentialResolver,
    OAuthCredentialResolver,
    StaticCredentialResolver,
    StaticCredentials,
)

# NEW — add these (from TASK-1403/1404):
from .grants import (
    Grant,
    GrantConfig,
    GrantStore,
    InMemoryGrantStore,
    GrantGuard,
    GuardDecision,
)
```

### Existing `__all__` (lines 50-75)
```python
__all__ = [
    "UserSession", "PermissionContext", "UserContext",
    "AbstractPermissionResolver", "DefaultPermissionResolver",
    "AllowAllResolver", "DenyAllResolver", "PBACPermissionResolver",
    "setup_pbac", "DatasetPolicyGuard", "PolicyRuleConfig",
    "AuthorizationRequired", "AgentAccessDenied",
    "CredentialResolver", "OAuthCredentialResolver",
    "StaticCredentialResolver", "StaticCredentials",
]
```

### Does NOT Exist
- ~~`Grant` in `__all__`~~ — not there yet. This task adds it.
- ~~`from .grants import ...`~~ — not there yet. This task adds it.

---

## Implementation Notes

### Exact Change
Add the import block and extend `__all__`. Group the new entries under a
`# Grants (bounded approval windows)` comment for clarity:

```python
# After existing imports, add:
from .grants import (
    Grant,
    GrantConfig,
    GrantStore,
    InMemoryGrantStore,
    GrantGuard,
    GuardDecision,
)

# In __all__, add:
    # Grants (bounded approval windows)
    "Grant",
    "GrantConfig",
    "GrantStore",
    "InMemoryGrantStore",
    "GrantGuard",
    "GuardDecision",
```

### Key Constraints
- Keep the import at module level (not lazy) — these are core auth types.
- Maintain alphabetical/logical ordering within the `__all__` list.
- Do NOT remove or reorder any existing entries.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/__init__.py` — the file to modify (current state verified above)
- `packages/ai-parrot/src/parrot/auth/grants.py` — source module (created by TASK-1403/1404)

---

## Acceptance Criteria

- [ ] `from parrot.auth import Grant, GrantConfig, GrantStore, InMemoryGrantStore, GrantGuard, GuardDecision` works.
- [ ] `__all__` includes all 6 new names.
- [ ] Existing imports from `parrot.auth` still work (zero regression).
- [ ] All grant tests pass: `pytest packages/ai-parrot/tests/tools/test_grants.py -v`.
- [ ] Full tool test suite green: `pytest packages/ai-parrot/tests/tools/ -v`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/__init__.py`.

---

## Test Specification

```python
# Smoke test — can be run inline or added to test_grants.py
def test_grant_exports():
    """All grant types are importable from parrot.auth."""
    from parrot.auth import (
        Grant,
        GrantConfig,
        GrantStore,
        InMemoryGrantStore,
        GrantGuard,
        GuardDecision,
    )
    assert Grant is not None
    assert GrantConfig is not None
    assert GrantStore is not None
    assert InMemoryGrantStore is not None
    assert GrantGuard is not None
    assert GuardDecision is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md` for full context
2. **Check dependencies** — verify TASK-1403, TASK-1404, TASK-1405 are all completed
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `packages/ai-parrot/src/parrot/auth/__init__.py` to confirm current state
   - Confirm `parrot/auth/grants.py` exports all 6 names
4. **Update status** in `sdd/tasks/index/tool-grants-bounded-approval.json` → `"in-progress"`
5. **Implement** the import + __all__ changes
6. **Verify** all acceptance criteria — especially the full test suite
7. **Move this file** to `sdd/tasks/completed/TASK-1406-grant-exports-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Added grant imports from `.grants` and extended `__all__` in
`parrot/auth/__init__.py`. All 6 names exported: Grant, GrantConfig, GrantStore,
InMemoryGrantStore, GrantGuard, GuardDecision. Full test suite: 30/30 pass.
Export smoke test passes. Ruff reports no issues.

**Deviations from spec**: None.
