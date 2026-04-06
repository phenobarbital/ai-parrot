# TASK-598: SubmitAction Auth Extension

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-597
**Assigned-to**: unassigned

---

## Context

Extends the existing `SubmitAction` model with an `auth: AuthConfig | None` field. This is a small but critical change — it modifies a core data model used throughout the form system. Must maintain backward compatibility (existing forms without `auth` continue to work).

Implements Spec Module 2.

---

## Scope

- Add `auth: AuthConfig | None = None` field to `SubmitAction` in `core/schema.py`
- Import `AuthConfig` from `core/auth` in `core/schema.py`
- Verify serialization: `SubmitAction.model_dump()` and `model_validate()` work with and without `auth`
- Update package-level `__init__.py` to export auth types

**NOT in scope**: Editing the forwarder, endpoints, or tests (separate tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` | MODIFY | Add `auth` field to `SubmitAction`, import `AuthConfig` |
| `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` | MODIFY | Export `AuthConfig`, `NoAuth`, `BearerAuth`, `ApiKeyAuth` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core/schema.py existing imports (line 8-16):
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict
from .constraints import DependencyRule, FieldConstraints
from .options import FieldOption, OptionsSource
from .types import FieldType, LocalizedString

# New import to add:
from .auth import AuthConfig  # created by TASK-597
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:89
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 99
    action_ref: str  # line 100
    method: str = "POST"  # line 101
    confirm_message: LocalizedString | None = None  # line 102
    # ADD: auth: AuthConfig | None = None
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py:31
# SubmitAction is already exported at line 31
# Auth types need to be added to imports and __all__
```

### Does NOT Exist
- ~~`SubmitAction.auth`~~ — does not exist yet; this task adds it
- ~~`from .auth import AuthConfig` in schema.py~~ — import does not exist yet

---

## Implementation Notes

### Key Constraints
- The `auth` field MUST default to `None` for backward compatibility
- Existing forms serialized without `auth` must deserialize correctly
- `SubmitAction` does NOT use `ConfigDict(extra="forbid")` — check before adding one
- The `AuthConfig` union type uses Pydantic's discriminated union on the `type` field

### Pattern to Follow
Simply add one field and one import. The change to `SubmitAction` is:
```python
from .auth import AuthConfig

class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None
    auth: AuthConfig | None = None  # NEW
```

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` — file to modify
- `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` — exports to update

---

## Acceptance Criteria

- [ ] `SubmitAction` has `auth: AuthConfig | None = None` field
- [ ] `SubmitAction(action_type="endpoint", action_ref="http://x")` still works (no auth)
- [ ] `SubmitAction(action_type="endpoint", action_ref="http://x", auth=BearerAuth(token_env="T"))` works
- [ ] `model_dump()` and `model_validate()` roundtrip correctly with auth
- [ ] `AuthConfig`, `NoAuth`, `BearerAuth`, `ApiKeyAuth` exported from `parrot.formdesigner`

---

## Test Specification

```python
# Quick smoke tests (full tests in TASK-605)
from parrot.formdesigner import SubmitAction, BearerAuth, ApiKeyAuth, NoAuth

def test_submit_action_without_auth():
    sa = SubmitAction(action_type="endpoint", action_ref="http://example.com")
    assert sa.auth is None
    d = sa.model_dump()
    assert d["auth"] is None

def test_submit_action_with_bearer():
    sa = SubmitAction(
        action_type="endpoint",
        action_ref="http://example.com",
        auth=BearerAuth(token_env="MY_TOKEN"),
    )
    assert sa.auth.type == "bearer"
    d = sa.model_dump()
    restored = SubmitAction.model_validate(d)
    assert restored.auth.token_env == "MY_TOKEN"

def test_submit_action_backward_compat():
    """Deserialize a dict without auth field."""
    d = {"action_type": "endpoint", "action_ref": "http://x", "method": "POST"}
    sa = SubmitAction.model_validate(d)
    assert sa.auth is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md`
2. **Check dependencies** — verify TASK-597 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `core/schema.py` and `__init__.py` before modifying
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the scope above
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/ -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
