# TASK-749: PermissionContext — Add `channel` Field

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 3 of the spec. The credential resolver needs to know which channel (telegram, agentalk, teams, api) the request originates from to construct the correct Redis key and OAuth callback. `PermissionContext` currently has `session`, `request_id`, and `extra` but no explicit `channel` field.

---

## Scope

- Add `channel: Optional[str] = None` field to the `PermissionContext` dataclass.
- Add a `@property` convenience accessor similar to existing `user_id`, `tenant_id`, `roles`.
- Update docstring with the new field.
- Write unit tests.

**NOT in scope**: Populating `channel` from integration handlers (that's Module 8/9), any Jira-specific logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/permission.py` | MODIFY | Add `channel` field to PermissionContext |
| `packages/ai-parrot/tests/unit/test_permission_context_channel.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import PermissionContext, UserSession  # verified: packages/ai-parrot/src/parrot/auth/permission.py:80,20
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py:79-110
@dataclass
class PermissionContext:
    session: UserSession  # line 108
    request_id: Optional[str] = None  # line 109
    extra: dict[str, Any] = field(default_factory=dict)  # line 110

    @property
    def user_id(self) -> str:  # line 112
    @property
    def tenant_id(self) -> str:  # line 117
    @property
    def roles(self) -> frozenset[str]:  # line 122
    def has_role(self, role: str) -> bool:  # line 127
    def has_any_role(self, roles: set[str] | frozenset[str]) -> bool:  # line 138

# packages/ai-parrot/src/parrot/auth/permission.py:19-77
@dataclass(frozen=True)
class UserSession:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    metadata: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
```

### Does NOT Exist
- ~~`PermissionContext.channel`~~ — field does NOT exist yet (this task adds it)

---

## Implementation Notes

### Pattern to Follow
Add `channel` after `request_id`, following the same pattern:

```python
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None  # NEW: telegram, agentalk, teams, api, etc.
    extra: dict[str, Any] = field(default_factory=dict)
```

### Key Constraints
- `channel` must be Optional with `None` default for backward compatibility.
- The field is a plain string (not an enum) to keep it extensible.
- Existing code that constructs `PermissionContext` without `channel` must continue to work.

---

## Acceptance Criteria

- [ ] `PermissionContext` has a `channel: Optional[str]` field
- [ ] `PermissionContext(session=..., channel="telegram")` works
- [ ] `PermissionContext(session=...)` works (backward compatible, channel=None)
- [ ] All existing tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot/tests/unit/test_permission_context_channel.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_permission_context_channel.py
import pytest
from parrot.auth.permission import PermissionContext, UserSession


@pytest.fixture
def session():
    return UserSession(
        user_id="user-123",
        tenant_id="acme",
        roles=frozenset({"jira.write"}),
    )


class TestPermissionContextChannel:
    def test_channel_default_is_none(self, session):
        ctx = PermissionContext(session=session)
        assert ctx.channel is None

    def test_channel_can_be_set(self, session):
        ctx = PermissionContext(session=session, channel="telegram")
        assert ctx.channel == "telegram"

    def test_channel_agentalk(self, session):
        ctx = PermissionContext(session=session, channel="agentalk")
        assert ctx.channel == "agentalk"

    def test_backward_compat_no_channel(self, session):
        ctx = PermissionContext(session=session, request_id="req-1")
        assert ctx.user_id == "user-123"
        assert ctx.channel is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `PermissionContext` fields at `permission.py` line ~108-110
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-749-permissioncontext-channel-field.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
