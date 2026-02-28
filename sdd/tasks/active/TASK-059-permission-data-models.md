# TASK-059: Permission Data Models

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec: Permission Data Models.

Define the foundational data structures for the permission system: `UserSession` and `PermissionContext`. These are lightweight, immutable structures that carry user identity and roles through the execution chain.

---

## Scope

- Create `parrot/auth/` directory if it doesn't exist
- Implement `UserSession` frozen dataclass with `user_id`, `tenant_id`, `roles` (frozenset)
- Implement `PermissionContext` dataclass wrapping session with request metadata
- Add property accessors on `PermissionContext` for convenience
- Write unit tests for both models

**NOT in scope**:
- Permission resolver (TASK-060)
- Decorator implementation (TASK-061)
- Integration with AbstractTool/Toolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/__init__.py` | CREATE | Package init with exports |
| `parrot/auth/permission.py` | CREATE | UserSession and PermissionContext |
| `tests/auth/__init__.py` | CREATE | Test package init |
| `tests/auth/test_permission.py` | CREATE | Unit tests for models |

---

## Implementation Notes

### Pattern to Follow
```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class UserSession:
    """Minimal session carrying identity and role claims.

    Immutable and hashable — safe for use as cache keys.
    """
    user_id: str
    tenant_id: str
    roles: frozenset[str]  # e.g. frozenset({'jira.manage', 'github.read'})
    metadata: dict = field(default_factory=dict)


@dataclass
class PermissionContext:
    """Request-scoped wrapper grouping session with extra context."""
    session: UserSession
    request_id: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def user_id(self) -> str:
        return self.session.user_id

    @property
    def tenant_id(self) -> str:
        return self.session.tenant_id

    @property
    def roles(self) -> frozenset[str]:
        return self.session.roles
```

### Key Constraints
- `UserSession` MUST be frozen (immutable)
- `roles` MUST be `frozenset` (hashable for caching)
- `PermissionContext` can be mutable (request-scoped)
- Include comprehensive docstrings

### References in Codebase
- `parrot/bots/base.py` — dataclass patterns
- `parrot/models/` — Pydantic/dataclass conventions

---

## Acceptance Criteria

- [ ] `parrot/auth/` directory exists with `__init__.py`
- [ ] `UserSession` is frozen dataclass
- [ ] `UserSession.roles` is `frozenset[str]`
- [ ] `PermissionContext` wraps `UserSession`
- [ ] `PermissionContext` has convenience properties
- [ ] Unit tests pass: `pytest tests/auth/test_permission.py -v`
- [ ] Import works: `from parrot.auth import UserSession, PermissionContext`

---

## Test Specification

```python
# tests/auth/test_permission.py
import pytest
from parrot.auth.permission import UserSession, PermissionContext


class TestUserSession:
    def test_frozen_immutable(self):
        """UserSession is immutable."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({'role-a'})
        )
        with pytest.raises(AttributeError):
            session.user_id = "changed"

    def test_roles_is_frozenset(self):
        """Roles must be frozenset."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({'admin', 'user'})
        )
        assert isinstance(session.roles, frozenset)
        assert 'admin' in session.roles

    def test_hashable(self):
        """UserSession is hashable (for cache keys)."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({'role-a'})
        )
        # Should not raise
        hash(session)

    def test_default_metadata(self):
        """Metadata defaults to empty dict."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset()
        )
        assert session.metadata == {}


class TestPermissionContext:
    def test_wraps_session(self):
        """Context wraps UserSession."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session)
        assert ctx.session is session

    def test_property_proxies(self):
        """Context proxies session properties."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session, request_id="req-123")
        assert ctx.user_id == "user-1"
        assert ctx.tenant_id == "tenant-1"
        assert ctx.roles == frozenset({'admin'})
        assert ctx.request_id == "req-123"

    def test_extra_metadata(self):
        """Context accepts extra metadata."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset()
        )
        ctx = PermissionContext(
            session=session,
            extra={"source": "api"}
        )
        assert ctx.extra["source"] == "api"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-059-permission-data-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
