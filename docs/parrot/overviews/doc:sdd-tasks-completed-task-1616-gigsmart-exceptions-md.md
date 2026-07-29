---
type: Wiki Overview
title: 'TASK-1616: GigSmart Typed Exception Hierarchy'
id: doc:sdd-tasks-completed-task-1616-gigsmart-exceptions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation module for all GigSmart error handling. Every other module in
  the toolkit
relates_to:
- concept: mod:parrot.exceptions
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: mentions
---

# TASK-1616: GigSmart Typed Exception Hierarchy

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation module for all GigSmart error handling. Every other module in the toolkit
depends on these exceptions. Implements Spec §7 (GraphQL Error Classification table)
and follows the `MassiveAPIError` pattern from `parrot_tools/massive/client.py`.

---

## Scope

- Implement a typed exception hierarchy rooted at `GigSmartError`
- Each exception carries an optional `status_code` and `message`
- `GigSmartRateLimitError` also carries `retry_after: int | None`
- Write unit tests for the hierarchy

**NOT in scope**: error classification logic (that belongs to TASK-1621 client), retry logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/__init__.py` | CREATE | Empty package init |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/exceptions.py` | CREATE | Exception hierarchy |
| `tests/tools/gigsmart/__init__.py` | CREATE | Test package init |
| `tests/tools/gigsmart/test_exceptions.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No framework imports needed — plain Python exceptions
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/massive/client.py:16-35
# REFERENCE PATTERN — do not import, just follow the structure
class MassiveAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):  # line 19
        super().__init__(message)
        self.status_code = status_code
        self.message = message

class MassiveRateLimitError(MassiveAPIError):  # line 25
    def __init__(self, message: str, retry_after: int | None = None):  # line 28
        super().__init__(message, status_code=429)
        self.retry_after = retry_after or 60

class MassiveTransientError(MassiveAPIError):  # line 33
    pass
```

### Does NOT Exist
- ~~`parrot.exceptions.BaseAPIError`~~ — no shared API error base class exists
- ~~`DeterministicGuard`~~ — does not exist in codebase
- ~~`GigSmartReconciliationError`~~ — from brainstorm SPEC; do NOT create this

---

## Implementation Notes

### Exception Classes to Create

```python
class GigSmartError(Exception):
    """Base for all GigSmart API errors."""
    def __init__(self, message: str, status_code: int | None = None): ...

class GigSmartAuthError(GigSmartError): ...           # UNAUTHENTICATED, FORBIDDEN
class GigSmartValidationError(GigSmartError): ...     # BAD_USER_INPUT
class GigSmartRateLimitError(GigSmartError):          # 429
    def __init__(self, message: str, retry_after: int | None = None): ...
class GigSmartNotFoundError(GigSmartError): ...       # NOT_FOUND
class GigSmartTransportError(GigSmartError): ...      # 5xx / network
class GigSmartGraphQLError(GigSmartError):            # generic GraphQL errors
    def __init__(self, message: str, errors: list[dict] | None = None): ...
class GigSmartConflictError(GigSmartError): ...       # CONFLICT
```

### Key Constraints
- Follow `MassiveAPIError` pattern exactly (message + status_code on base)
- `GigSmartRateLimitError` must store `retry_after` as attribute
- `GigSmartGraphQLError` must store the raw `errors` list from GraphQL response

---

## Acceptance Criteria

- [ ] All 8 exception classes defined
- [ ] `GigSmartError` is the common base
- [ ] `GigSmartRateLimitError.retry_after` attribute works
- [ ] `GigSmartGraphQLError.errors` stores raw error list
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_exceptions.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/`

---

## Test Specification

```python
import pytest
from parrot_tools.interfaces.gigsmart.exceptions import (
    GigSmartError, GigSmartAuthError, GigSmartValidationError,
    GigSmartRateLimitError, GigSmartNotFoundError, GigSmartTransportError,
    GigSmartGraphQLError, GigSmartConflictError,
)

class TestGigSmartExceptions:
    def test_base_error(self):
        err = GigSmartError("test", status_code=500)
        assert str(err) == "test"
        assert err.status_code == 500
        assert isinstance(err, Exception)

    def test_all_subclass_base(self):
        for cls in [GigSmartAuthError, GigSmartValidationError,
                    GigSmartRateLimitError, GigSmartNotFoundError,
                    GigSmartTransportError, GigSmartGraphQLError,
                    GigSmartConflictError]:
            assert issubclass(cls, GigSmartError)

    def test_rate_limit_retry_after(self):
        err = GigSmartRateLimitError("rate limited", retry_after=30)
        assert err.retry_after == 30
        assert err.status_code == 429

    def test_graphql_error_stores_errors(self):
        errors = [{"message": "not found", "extensions": {"code": "NOT_FOUND"}}]
        err = GigSmartGraphQLError("query failed", errors=errors)
        assert err.errors == errors
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `parrot_tools/interfaces/` directory exists
4. **Implement** the exception hierarchy
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-1616-gigsmart-exceptions.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*
